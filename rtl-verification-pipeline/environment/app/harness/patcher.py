"""Applies and reverts mutations for mutation adequacy testing."""
import shutil


def create_mutant(rtl_file, backup_path, original_code, mutant_code):
    """Create a mutant version by replacing original code with mutant code.

    Args:
        rtl_file: Path to the RTL source file
        backup_path: Where to save the original file backup
        original_code: The original correct line(s) to find
        mutant_code: The mutant line(s) to insert
    """
    shutil.copy2(rtl_file, backup_path)

    with open(rtl_file, 'r') as f:
        content = f.read()

    if original_code not in content:
        raise ValueError(f"Cannot find original code in {rtl_file}:\n  '{original_code}'")

    content = content.replace(original_code, mutant_code, 1)

    with open(rtl_file, 'w') as f:
        f.write(content)


def restore_original(rtl_file, backup_path):
    """Restore the original file from backup."""
    shutil.copy2(backup_path, rtl_file)
