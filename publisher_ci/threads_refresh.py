"""쓰레드 장기 토큰(60일) 자동 갱신 -> GitHub Secret THREADS_ACCESS_TOKEN 덮어쓰기.
- 새 토큰은 출력하지 않고 바로 gh 로 넘긴다(혹시 몰라 add-mask 도 등록).
- 토큰이 발급 후 24시간이 안 됐으면 메타가 거절하므로 매주 1회 실행.
"""
import json, os, re, subprocess, sys, urllib.parse, urllib.request, urllib.error

old = os.environ.get('THREADS_ACCESS_TOKEN', '')
if not os.environ.get('GH_TOKEN'):
    print('SECRETS_PAT 이 없어 갱신할 수 없습니다.'); sys.exit(1)
if not old:
    print('쓰레드 토큰이 없습니다.'); sys.exit(1)


def mask(s):
    return re.sub(r'access_token=[^&\s"\']+', 'access_token=***', str(s).replace(old, '***'))


q = urllib.parse.urlencode({'grant_type': 'th_refresh_token', 'access_token': old})
try:
    with urllib.request.urlopen(f'https://graph.threads.net/refresh_access_token?{q}', timeout=30) as r:
        d = json.load(r)
except urllib.error.HTTPError as e:
    print('갱신 실패:', mask(e.read().decode('utf-8', 'replace'))); sys.exit(1)
new = d.get('access_token', '')
if not new:
    print('갱신 응답에 토큰이 없습니다.'); sys.exit(1)
print(f'::add-mask::{new}')
r = subprocess.run(['gh', 'secret', 'set', 'THREADS_ACCESS_TOKEN', '--repo', os.environ['GITHUB_REPOSITORY']],
                   input=new, text=True, capture_output=True)
if r.returncode != 0:
    print('Secret 저장 실패:', mask(r.stderr).replace(new, '***')); sys.exit(1)
print(f'쓰레드 토큰 갱신 완료. 새 만료까지 약 {int(d.get("expires_in", 0)) // 86400}일')
