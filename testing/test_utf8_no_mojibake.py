import io
import re
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv'}
# Files that legitimately contain U+FFFD (an explicit assertion string).
FFFD_ALLOWED = {'test_supabase_migration_baseline.py'}
CORRUPT = re.compile(r'\?\?\?|\?\? \?\?')
THIS_FILE = Path(__file__).resolve()


def source_files(*suffixes):
    for path in ROOT.rglob('*'):
        if path.is_file() and path.suffix in suffixes and not SKIP_DIRS.intersection(path.relative_to(ROOT).parts):
            yield path


class Utf8NoMojibakeTest(unittest.TestCase):
    def test_strict_utf8_and_no_replacement_char(self):
        for path in source_files('.html', '.py'):
            raw = path.read_bytes()
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError as exc:
                self.fail(f'{path.relative_to(ROOT)} is not strict UTF-8: {exc}')
            if path.name not in FFFD_ALLOWED:
                self.assertNotIn('\ufffd', text, f'{path.relative_to(ROOT)} contains U+FFFD')

    def test_no_question_mark_korean_corruption_in_python_strings(self):
        for path in source_files('.py'):
            if path.resolve() == THIS_FILE:
                continue
            text = path.read_text(encoding='utf-8')
            try:
                tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
            except (tokenize.TokenError, IndentationError, SyntaxError):
                continue
            for tok in tokens:
                if tok.type == tokenize.STRING and CORRUPT.search(tok.string):
                    self.fail(f'{path.relative_to(ROOT)}:{tok.start[0]} corrupted string {tok.string[:60]!r}')

    def test_no_question_mark_korean_corruption_in_templates(self):
        for path in source_files('.html'):
            for no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                # `??` nullish coalescing is fine; runs of 3+ or "?? ??" are corruption.
                if CORRUPT.search(line):
                    self.fail(f'{path.relative_to(ROOT)}:{no} corrupted text {line.strip()[:80]!r}')


if __name__ == '__main__':
    unittest.main()
