"""Offline checks for the exact downloader and bundled YouTube JS solver."""
import importlib.metadata
import json
import logging
from pathlib import Path
import sys
import unittest

from packaging.requirements import Requirement
import yt_dlp
from yt_dlp.extractor.youtube import YoutubeIE
from yt_dlp.extractor.youtube.jsc._builtin.ejs import ScriptSource
from yt_dlp.extractor.youtube.jsc._builtin.node import NodeJCP


ROOT = Path(__file__).resolve().parents[2]


class DownloaderRuntimeRegression(unittest.TestCase):
    def test_installed_downloader_and_solver_match_requirements(self):
        for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8-sig').splitlines():
            requirement = Requirement(line)
            if requirement.name in ('yt-dlp', 'yt-dlp-ejs'):
                self.assertIn(importlib.metadata.version(requirement.name), requirement.specifier)

    @unittest.skipUnless(sys.platform == 'win32', 'Bundled Windows Node runtime')
    def test_official_solver_loads_and_executes_with_bundled_node(self):
        node = next((ROOT / 'runtime' / 'node').glob('*/node.exe'))
        with yt_dlp.YoutubeDL({'quiet': True, 'cachedir': False,
                              'js_runtimes': {'node': {'path': str(node)}}}) as ydl:
            provider = NodeJCP(YoutubeIE(ydl), logging.getLogger(__name__), {})
            self.assertTrue(provider.is_available())
            lib, core = provider._lib_script, provider._core_script
            self.assertEqual(lib.source, ScriptSource.PYPACKAGE)
            self.assertEqual(core.source, ScriptSource.PYPACKAGE)
            # Loading through yt-dlp also validates the official script hashes.
            script = (lib.code + '\nObject.assign(globalThis, lib);\n' + core.code
                      + '\nconsole.log(JSON.stringify({solverLoaded: typeof jsc === "function"}));')
            self.assertTrue(json.loads(provider._run_js_runtime(script))['solverLoaded'])


if __name__ == '__main__': unittest.main(verbosity=2)
