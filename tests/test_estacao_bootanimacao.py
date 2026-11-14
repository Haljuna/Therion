import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts' / 'estacao' / 'tablet'))
import bootanimacao  # noqa: E402

FUNDO = (0x0d, 0x0a, 0x18)


class TestBootanimacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.zip = bootanimacao.gerar(Path(tempfile.mkdtemp()))

    def test_desc_txt(self):
        with zipfile.ZipFile(self.zip) as z:
            self.assertEqual(z.read('desc.txt').decode(), '1024 600 12\np 1 0 part0\np 0 0 part1\n')

    def test_sem_compressao(self):
        with zipfile.ZipFile(self.zip) as z:
            self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist()))

    def test_quantidade_de_quadros(self):
        with zipfile.ZipFile(self.zip) as z:
            n = z.namelist()
            self.assertEqual(len([x for x in n if x.startswith('part0/') and x.endswith('.png')]), 30)
            self.assertEqual(len([x for x in n if x.startswith('part1/') and x.endswith('.png')]), 24)

    def test_tamanho_fundo_e_anel_dentro_da_altura(self):
        with zipfile.ZipFile(self.zip) as z:
            img = Image.open(io.BytesIO(z.read('part1/00000.png'))).convert('RGB')
        self.assertEqual(img.size, (1024, 600))
        self.assertEqual(img.getpixel((2, 2)), FUNDO)
        linhas = [y for y in range(600) if any(img.getpixel((x, y)) != FUNDO for x in range(312, 712, 4))]
        self.assertGreater(min(linhas), 60)
        self.assertLess(max(linhas), 540)


if __name__ == '__main__':
    unittest.main()
