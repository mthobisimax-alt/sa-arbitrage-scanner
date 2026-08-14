# SA Arbitrage Scanner Web V1

Browser-first version. No APK and no app installation required.

Run locally:
1. Install Python 3.10+.
2. Open terminal in this folder.
3. `pip install -r requirements.txt`
4. `python app.py`
5. Open `http://127.0.0.1:8787`

Demo mode is ON and shows a sample mathematical arbitrage.

For a real browser-accessible deployment, place this FastAPI service on a VPS/cloud host with HTTPS, then open the HTTPS address from the Huawei browser.

The bookmaker feed placeholders must be replaced with authorised/public odds feeds. Do not bypass CAPTCHAs, authentication, rate limits or access controls.
