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
import threading


class MediaDownloadRegression(unittest.TestCase):
    @staticmethod
    def response(data=b'complete', mime='image/jpeg'):
        response=MagicMock();response.headers={'Content-Type':mime}
        response.iter_content.return_value=iter([data])
        request=MagicMock();request.__enter__.return_value=response
        return request,response

    def test_ssl_eof_and_connection_reset_retry_only_failed_transfer(self):
        request,response=self.response()
        progress=MagicMock()
        failures=[main.requests.exceptions.SSLError('UNEXPECTED_EOF_WHILE_READING'),
                  main.requests.ConnectionError(ConnectionResetError(10054,'connection reset'))]
        with tempfile.TemporaryDirectory() as folder,patch.object(main.requests,'get',side_effect=failures+[request]) as get,patch.object(main.time,'sleep') as sleep:
            result=main.download_media_parallel([('https://scontent.cdninstagram.com/photo.heic','image','')],
                folder,'post',progress,proxy='http://127.0.0.1:9876')
            self.assertEqual(result,(1,1));self.assertEqual(get.call_count,3)
            self.assertEqual((Path(folder)/'post_1.jpg').read_bytes(),b'complete')
            self.assertFalse(list(Path(folder).glob('*.part')))
            progress.assert_called_once_with(1,1)
            self.assertEqual([c.args[0] for c in sleep.call_args_list],[.5,1.0])
            for call in get.call_args_list:
                self.assertEqual(call.kwargs['proxies'],{'http':'http://127.0.0.1:9876','https':'http://127.0.0.1:9876'})
                self.assertNotIn('verify',call.kwargs)
            request.__exit__.assert_called_once()

    def test_partial_read_is_removed_before_retry_and_existing_file_is_safe(self):
        first,interrupted=self.response()
        second,complete=self.response(b'whole-file')
        def chunks():
            yield b'partial-'
            raise main.requests.exceptions.ChunkedEncodingError('incomplete read')
        interrupted.iter_content.side_effect=lambda **_:chunks()
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'post_1.jpg';target.write_bytes(b'original')
            def request(*_,**__):
                self.assertEqual(target.read_bytes(),b'original')
                self.assertFalse(list(Path(folder).glob('*.part')))
                return first if request.count==0 else second
            request.count=0
            def next_request(*args,**kwargs):
                result=request(*args,**kwargs);request.count+=1;return result
            with patch.object(main.requests,'get',side_effect=next_request),patch.object(main.time,'sleep'):
                self.assertEqual(main.download_media_parallel([('https://cdn.example/photo.jpg','image','')],folder),(1,1))
            self.assertEqual(target.read_bytes(),b'whole-file');self.assertFalse(list(Path(folder).glob('*.part')))
            self.assertEqual(request.count,2)
            first.__exit__.assert_called_once();second.__exit__.assert_called_once()

    def test_missing_file_and_certificate_errors_do_not_retry(self):
        missing=main.requests.Response();missing.status_code=404
        for error in (main.requests.HTTPError('missing',response=missing),
                      main.requests.exceptions.SSLError('CERTIFICATE_VERIFY_FAILED')):
            with self.subTest(error=type(error).__name__),patch.object(main.time,'sleep') as sleep:
                operation=MagicMock(side_effect=error)
                with self.assertRaises(type(error)):main._retry_media_transfer(operation,'test')
                operation.assert_called_once();sleep.assert_not_called()

    def test_retry_budget_exhaustion_reports_one_failure_without_overwriting(self):
        progress=MagicMock()
        with tempfile.TemporaryDirectory() as folder,patch.object(main.requests,'get',side_effect=main.requests.exceptions.SSLError('EOF')) as get,patch.object(main.time,'sleep'):
            target=Path(folder)/'post_1.jpg';target.write_bytes(b'original')
            self.assertEqual(main.download_media_parallel([('https://cdn.example/photo.jpg','image','')],folder,progress_callback=progress),(0,1))
            self.assertEqual(get.call_count,3);self.assertEqual(target.read_bytes(),b'original')
            self.assertFalse(list(Path(folder).glob('*.part')));progress.assert_called_once_with(1,1)

    def test_transient_server_error_retries_with_response_closed(self):
        first,response=self.response();second,_=self.response()
        unavailable=main.requests.Response();unavailable.status_code=503
        response.raise_for_status.side_effect=main.requests.HTTPError('temporarily unavailable',response=unavailable)
        with tempfile.TemporaryDirectory() as folder,patch.object(main.requests,'get',side_effect=[first,second]),patch.object(main.time,'sleep'):
            self.assertEqual(main.download_media_parallel([('https://cdn.example/photo.jpg','image','')],folder),(1,1))
            first.__exit__.assert_called_once();second.__exit__.assert_called_once()

    def test_successful_sibling_is_not_downloaded_again_when_another_retries(self):
        counts={};lock=threading.Lock()
        def get(url,**_):
            with lock:counts[url]=counts.get(url,0)+1;attempt=counts[url]
            if url.endswith('second.jpg') and attempt==1:raise main.requests.ConnectionError('reset')
            return self.response(url.encode())[0]
        media=[(f'https://cdn.example/{name}.jpg','image','') for name in ('first','second')]
        with tempfile.TemporaryDirectory() as folder,patch.object(main.requests,'get',side_effect=get),patch.object(main.time,'sleep'):
            self.assertEqual(main.download_media_parallel(media,folder),(2,2))
            self.assertEqual([counts[m[0]] for m in media],[1,2])

    def test_instagram_preview_recovers_from_temporary_connection_error(self):
        image=BytesIO();Image.new('RGB',(12,16),'pink').save(image,format='PNG')
        request,response=self.response();response.content=image.getvalue()
        context=SimpleNamespace(_closing=False,_thumbnail_generation=7,
            _apply_instagram_preview=MagicMock(),_finish_instagram_previews=MagicMock(),_schedule_media_callback=MagicMock())
        url='https://scontent.cdninstagram.com/photo.jpg'
        with patch.object(main.requests,'get',side_effect=[main.requests.ConnectionError('reset'),request]) as get,patch.object(main.time,'sleep'):
            main.InstagramDownloaderApp._load_instagram_previews(context,[(url,'image','')],7,'http://127.0.0.1:9876')
            self.assertEqual(get.call_count,2)
            args=context._schedule_media_callback.call_args_list[0].args
            self.assertIs(args[0],context._apply_instagram_preview)
            self.assertEqual(args[2][:3],(url,12,16));self.assertIsInstance(args[2][3],Image.Image)
            self.assertEqual(get.call_args.kwargs['proxies'],{'http':'http://127.0.0.1:9876','https':'http://127.0.0.1:9876'})
            request.__exit__.assert_called_once()

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
