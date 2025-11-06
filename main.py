import requests
import re
import os
import zoneinfo
import traceback
from datetime import datetime, timedelta
from html import unescape
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

load_dotenv()

API_KEY = os.getenv("API_KEY", "")
MANADA_USER = os.getenv("MANADA_USER", "")
MANADA_PWD = os.getenv("MANADA_PWD", "")
AUTH_URL = os.getenv("AUTH_URL", "")
MANADA_URL = os.getenv("MANADA_URL", "")

if not all([API_KEY, MANADA_USER, MANADA_PWD, AUTH_URL, MANADA_URL]):
    print("Not all variables are set")
    exit(1)

DUE_FORMAT = "%Y-%m-%d %H:%M"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/116.0"

# FastAPI setup
app = FastAPI(title="Manada Assignment API")

def get_shib() -> dict[str, str]:
    s = requests.session()

    headers = {
        "User-Agent": UA,
    }

    r = s.get(f"{MANADA_URL}/ct/home", headers=headers)

    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "shib_idp_ls_exception.shib_idp_session_ss": "",
        "shib_idp_ls_success.shib_idp_session_ss": "true",
        "shib_idp_ls_value.shib_idp_session_ss": "",
        "shib_idp_ls_exception.shib_idp_persistent_ss": "",
        "shib_idp_ls_success.shib_idp_persistent_ss": "true",
        "shib_idp_ls_value.shib_idp_persistent_ss": "",
        "shib_idp_ls_supported": "true",
        "_eventId_proceed": "",
    }

    r = s.post(
        f"{AUTH_URL}?execution=e1s1",
        headers=headers,
        data=data,
    )

    ######

    data = {
        "j_username": MANADA_USER,
        "j_password": MANADA_PWD,
        "_eventId_proceed": "",
    }

    r = s.post(
        f"{AUTH_URL}?execution=e1s2",
        headers=headers,
        data=data,
    )

    ######

    data = {
        "shib_idp_ls_exception.shib_idp_session_ss": "",
        "shib_idp_ls_success.shib_idp_session_ss": "true",
        "_eventId_proceed": "",
    }

    r = s.post(
        f"{AUTH_URL}?execution=e1s3",
        headers=headers,
        data=data,
    )

    relay_state, saml = map(lambda x: x[7:-3], re.findall(r'value=".*"/>', r.text)[:2])

    ######

    data = {"RelayState": unescape(relay_state), "SAMLResponse": saml}

    r = s.post(
        f"{MANADA_URL}/Shibboleth.sso/SAML2/POST",
        headers=headers,
        data=data,
    )
    shib_key = [
        k for k in s.cookies.get_dict().keys() if k.startswith("_shibsession_")
    ][0]
    return {f"{shib_key}": s.cookies.get_dict()[shib_key]}

def fetch_assignments():
    headers = {"User-Agent": UA}

    cookies = get_shib()

    r = requests.get(
        f"{MANADA_URL}/ct/home_library_query",
        cookies=cookies,
        headers=headers,
    )

    dues = []
    for e in r.text.split("myassignments-title")[1:]:
        due = re.findall(r'td-period">(.*)</td>', e)
        if not (due and len(due) >= 2 and due[1].startswith("202")):
            continue
        due_iso = due[1].strip().replace(" ", "T")
        due_readable = datetime.strptime(f"{due[1].strip()} +09:00", f"{DUE_FORMAT} %z")
        due_remain = due_readable - datetime.now(tz=zoneinfo.ZoneInfo("Asia/Tokyo"))

        if due_remain < timedelta(days=0):
            continue
        if due_remain < timedelta(days=7):
            url_name = re.search(r'<a href="(.+)">(.+?)</a>', e)
            course = re.search(r'class="mycourse-title"><.*>(.*)</a>', e)
            if not url_name or not course:
                continue

            dues.append({
                "title": url_name.group(2).replace("amp;", ""),
                "course": course.group(1).replace("amp;", ""),
                "deadline": due_iso,
                "remaining": {
                    "days": due_remain.days,
                    "hours": due_remain.seconds // 3600,
                    "minutes": (due_remain.seconds // 60) % 60,
                },
                "url": f"{MANADA_URL}/ct/" + url_name.group(1),
            })
    return dues


# endpoints
@app.get("/assignments")
async def get_assignments(request: Request):
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    try:
        dues = fetch_assignments()
        return JSONResponse(content=dues)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def root():
    return {"status": "ok", "message": "Use /assignments with Authorization header"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
