import marshal
import pathlib
import importlib.util
import types

src = pathlib.Path(r"C:\Users\qqq\Documents\ChatGPT\ADC\pyz_extract_22c\translator_desktop.pyc")
out = pathlib.Path(r"C:\Users\qqq\Documents\ChatGPT\ADC\patch_sticker_22\translator_desktop_patched.pyc")
root = marshal.loads(src.read_bytes())
old_suffix = (".png", ".jpg", ".jpeg", ".webp")
new_suffix = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".ico", ".avif", ".jfif")
old_patterns = {"*.png *.jpg *.jpeg *.webp"}
new_pattern = "*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff *.ico *.avif *.jfif"
changes = {"suffix_tuple": 0, "pattern": 0}

def patch_const(value):
    if value == old_suffix:
        changes["suffix_tuple"] += 1
        return new_suffix
    if isinstance(value, str) and value in old_patterns:
        changes["pattern"] += 1
        return new_pattern
    if isinstance(value, tuple):
        return tuple(patch_const(v) for v in value)
    if isinstance(value, types.CodeType):
        consts = tuple(patch_const(v) for v in value.co_consts)
        return value.replace(co_consts=consts)
    return value

patched = patch_const(root)
print(changes)
header = importlib.util.MAGIC_NUMBER + b"\0" * 12
out.write_bytes(header + marshal.dumps(patched))
print(out, out.stat().st_size)
