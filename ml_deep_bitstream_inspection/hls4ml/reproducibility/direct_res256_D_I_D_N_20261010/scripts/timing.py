import re
def validate_timing_report(path):
    text = path.read_text(errors='replace')
    # Vivado 2024.2 writes "All user specified timing constraints are met."
    if re.search(r'timing constraints are not met|not all user specified timing constraints are met', text, re.I):
        raise RuntimeError('Timing failure: '+str(path))
    if not re.search(r'^\s*(?:All user specified )?Timing constraints are met\.?\s*$', text, re.I | re.M):
        raise RuntimeError('Cannot verify timing: '+str(path))
