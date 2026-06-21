# Post URL Capture

Use this when the operator wants a 3.5 to 4 day or weekly campaign URL sheet.

```bash
PYTHONPATH=backend backend/.venv/bin/python script/export_post_url_capture.py --window-days 4
```

The output is written under `artifacts/post-url-capture/` so real post URLs stay local unless the operator chooses to share them. Each campaign gets one row per scheduled/posted clip with columns for TikTok, Instagram, YouTube, Facebook, and X. TikTok can be filled from Upload-Post responses once live posts return public URLs. The other platform columns are manual paste slots while those accounts are still locked or warming up.

For a weekly sheet:

```bash
PYTHONPATH=backend backend/.venv/bin/python script/export_post_url_capture.py --window-days 7
```
