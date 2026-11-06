"""매주 토큰 유효성 점검. 실패하면 종료코드 1 -> GitHub가 저장소 주인에게 실패 메일을 보냄."""
import json, os, re, sys, urllib.parse, urllib.request, urllib.error

tok = os.environ.get('IG_ACCESS_TOKEN', '')
uid = os.environ.get('IG_USER_ID', '')


def mask(s):
    return re.sub(r'access_token=[^&\s"\']+', 'access_token=***', str(s).replace(tok, '***') if tok else str(s))


try:
    q = urllib.parse.urlencode({'fields': 'username,followers_count', 'access_token': tok})
    with urllib.request.urlopen(f'https://graph.facebook.com/{uid}?{q}', timeout=30) as r:
        d = json.load(r)
    print('인스타 토큰 정상:', d.get('username'), '팔로워', d.get('followers_count'))
except urllib.error.HTTPError as e:
    print('인스타 토큰 오류:', mask(e.read().decode('utf-8', 'replace'))); sys.exit(1)
except Exception as e:
    print('인스타 토큰 점검 실패:', mask(e)); sys.exit(1)

th = os.environ.get('THREADS_ACCESS_TOKEN', '')
if th:
    try:
        q = urllib.parse.urlencode({'fields': 'username', 'access_token': th})
        with urllib.request.urlopen(f'https://graph.threads.net/v1.0/me?{q}', timeout=30) as r:
            print('쓰레드 토큰 정상:', json.load(r).get('username'))
    except Exception as e:
        print('쓰레드 토큰 오류:', mask(e).replace(th, '***')); sys.exit(1)
