"""Media CDN handling and per-job cookie copies, without external requests."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import main
from video_tasks import VideoTask, VideoOptions
from PIL import Image
from io import BytesIO


class MediaDownloadRegression(unittest.TestCase):
    def test_tiktok_context_proxy_and_image_mime_survive_download(self):
        image = BytesIO(); Image.new('RGB', (8, 8), 'pink').save(image, format='WEBP')
        response = MagicMock(); response.headers = {'Content-Type': 'image/webp'}
        response.iter_content.return_value = iter([image.getvalue()])
        request = MagicMock(); request.__enter__.return_value = response
        url = 'https://cdn.example/signed.image?signature=keep'
        context = {'User-Agent': 'original-agent', 'Referer': 'https://www.tiktok.com/@creator/photo/12345', 'Cookie': 'scoped=value'}
        with tempfile.TemporaryDirectory() as folder, patch.object(main.requests, 'get', return_value=request) as get:
            self.assertEqual(main.download_media_parallel([(url, 'image', url)], folder, 'tiktok_12345',
                             request_headers=lambda resource: context if resource == url else {}, proxy='http://127.0.0.1:9876'), (1, 1))
            output = Path(folder) / 'tiktok_12345_1.png'
            with Image.open(output) as actual: self.assertEqual(actual.format, 'PNG')
            self.assertFalse(list(Path(folder).glob('*.part')))
            self.assertEqual(get.call_args.kwargs['headers'], context)
            self.assertEqual(get.call_args.kwargs['proxies'], {'http': 'http://127.0.0.1:9876', 'https': 'http://127.0.0.1:9876'})

    def test_x_image_format_and_headers_are_preserved(self):
        response=MagicMock();response.iter_content.return_value=iter([b'newpng'])
        request=MagicMock();request.__enter__.return_value=response
        with tempfile.TemporaryDirectory() as folder,patch.object(main.requests,'get',return_value=request) as get:
            result=main.download_media_parallel([('https://pbs.twimg.com/media/id?format=png&name=orig','image','')],folder,'x_123')
            self.assertEqual(result,(1,1))
            self.assertEqual((Path(folder)/'x_123_1.png').read_bytes(),b'newpng')
            self.assertEqual(get.call_args.kwargs['headers']['Referer'],'https://x.com/')
            self.assertTrue(get.call_args.kwargs['stream'])

    def test_interrupted_media_transfer_keeps_existing_file(self):
        response=MagicMock();response.iter_content.side_effect=OSError('interrupted')
        request=MagicMock();request.__enter__.return_value=response
        with tempfile.TemporaryDirectory() as folder,patch.object(main.requests,'get',return_value=request):
            target=Path(folder)/'x_123_1.jpg';target.write_bytes(b'original')
            result=main.download_media_parallel([('https://pbs.twimg.com/media/id?format=jpg','image','')],folder,'x_123')
            self.assertEqual(result,(0,1));self.assertEqual(target.read_bytes(),b'original')
            self.assertFalse(list(Path(folder).glob('*.part')))

    def test_video_workers_get_private_cookie_copies(self):
        seen=[];paths=[];original=b'# Netscape HTTP Cookie File\n'
        class Downloader:
            def __init__(self,ffmpeg_path,cookie_file): self.cookie=Path(cookie_file)
            def download(self,*args,**kwargs):
                seen.append(self.cookie.read_bytes());paths.append(self.cookie)
                self.cookie.write_bytes(b'changed by downloader');return True
        context=SimpleNamespace(yt_downloader=SimpleNamespace(ffmpeg_path='ffmpeg'))
        options=VideoOptions('output',cookie_data=original)
        with patch.object(main,'YouTubeDownloader',Downloader):
            for index in range(2):
                task=VideoTask(str(index),'https://youtu.be/example',options)
                self.assertTrue(main.InstagramDownloaderApp._run_video_task(context,task,lambda _:None,lambda _:None))
        self.assertEqual(seen,[original,original]);self.assertNotEqual(paths[0],paths[1])
        self.assertTrue(all(not path.exists() for path in paths))
