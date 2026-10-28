"""Small, explicit rich-text format and bounded image decoding for all boards."""
from io import BytesIO
import warnings
import bleach
from markupsafe import Markup, escape
from PIL import Image, ImageOps, UnidentifiedImageError

TAGS = {'p', 'br', 'strong', 'em', 'u', 's', 'h2', 'h3', 'ol', 'ul', 'li', 'blockquote', 'a'}


def clean_html(value):
    return bleach.clean(value, tags=TAGS, attributes={'a': ['href', 'title']},
                        protocols={'https', 'http', 'mailto'}, strip=True, strip_comments=True)


def render_content(value, content_format='plain'):
    return Markup(clean_html(value or '')) if content_format == 'html' else escape(value or '')


def validate_content(value, content_format):
    if content_format not in ('plain', 'html') or not isinstance(value, str) or len(value) > 50000:
        raise ValueError('본문 형식 또는 길이를 확인해주세요. 최대 50,000자입니다.')
    value = clean_html(value) if content_format == 'html' else value.strip()
    text = bleach.clean(value, tags=[], strip=True) if content_format == 'html' else value
    if not text.replace('&nbsp;', ' ').strip():
        raise ValueError('본문을 입력해주세요.')
    return value


def prepare_image(file):
    raw = file.read(10 * 1024 * 1024 + 1)
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError('이미지는 파일당 10MB 이하여야 합니다.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if image.format not in {'JPEG', 'PNG', 'WEBP', 'GIF'} or image.width * image.height > 25_000_000:
                    raise ValueError('JPG·PNG·WebP·GIF, 2,500만 화소 이하 이미지를 선택해주세요.')
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                # A decoded still image removes hidden payloads, EXIF location and animation bombs.
                image = ImageOps.exif_transpose(image).convert('RGBA' if 'A' in image.getbands() else 'RGB')
                image.thumbnail((2400, 2400))
                output = BytesIO()
                image.save(output, format='WEBP', quality=85, method=4)
                return output.getvalue(), 'image/webp', 'webp'
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('읽을 수 없는 이미지입니다. 다른 이미지로 다시 시도해주세요.') from exc
