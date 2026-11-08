"""GitHub Actions 예약 게시 스크립트 (jd-insta-public).

- queue/<KST날짜>/<slot>.json 중 예약 시간이 지난 것을 인스타그램(그리고 설정 시 쓰레드)에 게시
- 중복 방지: 게시 전에 state/<날짜>/<slot>.claimed 를 커밋·푸시하고, 끝나면 .done 기록
  -> 이미 claimed/done 이 있으면 절대 다시 게시하지 않음
- 하루 최대 4개, 실패 시 1회 재시도 후 다음 회차로
- 예약 시간보다 4시간 넘게 늦으면 게시하지 않고 skipped_late 로 기록
- 토큰은 환경변수(GitHub Secrets)에서만 읽고, 출력은 모두 마스킹
- 저장소 루트에 PAUSE 파일이 있으면 아무것도 게시하지 않음
"""
import datetime as dt, json, os, re, subprocess, sys, time
import urllib.error, urllib.parse, urllib.request

KST = dt.timezone(dt.timedelta(hours=9))
REPO_RAW = 'https://raw.githubusercontent.com/daegustar123-source/jd-insta-public/main/'
GRAPH = 'https://graph.facebook.com'
THREADS = 'https://graph.threads.net/v1.0'
DAILY_LIMIT = 4
LATE_LIMIT_H = 4

DRY = os.environ.get('DRY_RUN') == '1'   # 모의 실행: API 호출·커밋 없이 판단만 출력
TOKENS = [os.environ.get(k, '') for k in ('IG_ACCESS_TOKEN', 'THREADS_ACCESS_TOKEN')]


def mask(s):
    s = str(s)
    for t in TOKENS:
        if t:
            s = s.replace(t, '***')
    return re.sub(r'access_token=[^&\s"\']+', 'access_token=***', s)


def say(*a):
    print(mask(' '.join(str(x) for x in a)), flush=True)


def git(*a, check=True):
    return subprocess.run(['git', *a], check=check, capture_output=True, text=True)


def commit_push(paths, msg):
    if DRY:
        say(f'[모의] 커밋 생략: {msg}'); return
    git('add', '--', *paths)
    if not git('diff', '--cached', '--name-only').stdout.strip():
        return
    git('commit', '-q', '-m', msg)
    for _ in range(4):
        if git('push', '-q', check=False).returncode == 0:
            return
        git('pull', '-q', '--rebase', check=False)
    raise RuntimeError('push 실패')


def api(method, url, params, token):
    body = urllib.parse.urlencode(dict(params, access_token=token)).encode()
    req = urllib.request.Request(url if method == 'POST' else f'{url}?{body.decode()}',
                                 data=body if method == 'POST' else None, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(mask(e.read().decode('utf-8', 'replace'))) from None


# ---------------- Instagram ----------------
def ig_wait(cid, token):
    for _ in range(60):
        st = api('GET', f'{GRAPH}/{cid}', {'fields': 'status_code'}, token).get('status_code')
        if st == 'FINISHED':
            return
        if st in ('ERROR', 'EXPIRED'):
            raise RuntimeError(f'컨테이너 {st}')
        time.sleep(5)
    raise RuntimeError('컨테이너 시간 초과')


def ig_publish(item, urls):
    uid, token = os.environ['IG_USER_ID'], os.environ['IG_ACCESS_TOKEN']
    kind, cap = item['kind'], item.get('caption', '')
    if kind == 'carousel':
        kids = []
        for u in urls:
            c = api('POST', f'{GRAPH}/{uid}/media', {'image_url': u, 'is_carousel_item': 'true'}, token)
            ig_wait(c['id'], token); kids.append(c['id'])
        cont = api('POST', f'{GRAPH}/{uid}/media', {'media_type': 'CAROUSEL', 'children': ','.join(kids), 'caption': cap}, token)
    elif kind == 'story':
        cont = api('POST', f'{GRAPH}/{uid}/media', {'image_url': urls[0], 'media_type': 'STORIES'}, token)
    else:
        cont = api('POST', f'{GRAPH}/{uid}/media', {'image_url': urls[0], 'caption': cap}, token)
    ig_wait(cont['id'], token)
    pub = api('POST', f'{GRAPH}/{uid}/media_publish', {'creation_id': cont['id']}, token)
    link = api('GET', f'{GRAPH}/{pub["id"]}', {'fields': 'permalink'}, token).get('permalink')
    return pub['id'], link


# ---------------- Threads ----------------
def th_publish(item, urls):
    token = os.environ.get('THREADS_ACCESS_TOKEN')
    text = item.get('threads_text')
    if not token or not text:
        return None
    me = 'me'
    if item['kind'] == 'carousel' and len(urls) > 1:
        kids = [api('POST', f'{THREADS}/{me}/threads', {'media_type': 'IMAGE', 'image_url': u, 'is_carousel_item': 'true'}, token)['id'] for u in urls[:10]]
        time.sleep(10)
        c = api('POST', f'{THREADS}/{me}/threads', {'media_type': 'CAROUSEL', 'children': ','.join(kids), 'text': text}, token)
    else:
        c = api('POST', f'{THREADS}/{me}/threads', {'media_type': 'IMAGE', 'image_url': urls[0], 'text': text}, token)
    time.sleep(30)  # 쓰레드 권장 대기
    pub = api('POST', f'{THREADS}/{me}/threads_publish', {'creation_id': c['id']}, token)
    link = api('GET', f'{THREADS}/{pub["id"]}', {'fields': 'permalink'}, token).get('permalink')
    return pub['id'], link


def th_reply(item, parent_id):
    """게시 직후 같은 계정으로 자기 댓글(답글) 1개. 실패해도 본 게시물에는 영향 없음."""
    token = os.environ.get('THREADS_ACCESS_TOKEN')
    text = (item.get('threads_reply') or '').strip()
    if not token or not text:
        return None
    c = api('POST', f'{THREADS}/me/threads', {'media_type': 'TEXT', 'text': text, 'reply_to_id': parent_id}, token)
    time.sleep(10)
    pub = api('POST', f'{THREADS}/me/threads_publish', {'creation_id': c['id']}, token)
    return pub['id']


def main():
    if os.path.exists('PAUSE'):
        say('PAUSE 파일이 있어 게시를 건너뜁니다.'); return
    if not DRY:
        git('config', 'user.name', 'jd-insta-bot')
        git('config', 'user.email', 'jd-insta-bot@users.noreply.github.com')
    now = dt.datetime.fromisoformat(os.environ['MOCK_NOW']) if DRY and os.environ.get('MOCK_NOW') else dt.datetime.now(KST)
    day = now.date().isoformat()
    qdir, sdir, rfile = f'queue/{day}', f'state/{day}', f'results/{day}.jsonl'
    if not os.path.isdir(qdir):
        say('오늘 예약 없음', day); return
    os.makedirs(sdir, exist_ok=True); os.makedirs('results', exist_ok=True)
    threads_on = os.environ.get('THREADS_ENABLED', 'false').lower() == 'true'

    def record(entry):
        entry = {'time': dt.datetime.now(KST).isoformat(timespec='seconds'), **entry}
        with open(rfile, 'a', encoding='utf-8') as f:
            f.write(mask(json.dumps(entry, ensure_ascii=False)) + '\n')

    items = sorted((json.load(open(os.path.join(qdir, f), encoding='utf-8')) for f in os.listdir(qdir) if f.endswith('.json')),
                   key=lambda x: x['scheduled_kst'])
    for item in items:
        slot = item['slot']
        claimed, done = f'{sdir}/{slot}.claimed', f'{sdir}/{slot}.done'
        if os.path.exists(claimed) or os.path.exists(done):
            continue
        when = dt.datetime.fromisoformat(item['scheduled_kst'])
        if now < when:
            continue
        if len([f for f in os.listdir(sdir) if f.endswith('.done')]) >= DAILY_LIMIT:
            record({'slot': slot, 'platform': 'instagram', 'status': 'skipped', 'reason': f'하루 {DAILY_LIMIT}개 제한'})
            open(done, 'w').write('limit'); commit_push([done, rfile], f'skip {day} {slot} (limit)'); continue
        if now - when > dt.timedelta(hours=LATE_LIMIT_H):
            record({'slot': slot, 'platform': 'instagram', 'status': 'skipped_late', 'scheduled': item['scheduled_kst']})
            open(done, 'w').write('late'); commit_push([done, rfile], f'skip {day} {slot} (late)'); continue

        if DRY:
            say(f'[모의] {now:%H:%M} 기준 게시 대상: {slot} ({item["kind"]}, 예약 {when:%H:%M}, 이미지 {len(item["images"])}장)'
                f' -> 쓰레드 {"함께 게시" if threads_on and item.get("threads_text") else "안 함"}')
            continue
        # 1) 선점 기록 먼저 푸시 -> 다른 실행이 같은 게시물을 올리지 못함
        open(claimed, 'w').write(now.isoformat())
        commit_push([claimed], f'claim {day} {slot}')
        urls = [REPO_RAW + p for p in item['images']]
        ok = False
        for attempt in (1, 2):
            try:
                mid, link = ig_publish(item, urls)
                record({'slot': slot, 'platform': 'instagram', 'status': 'success', 'kind': item['kind'],
                        'media_id': mid, 'permalink': link, 'label': item.get('label', '')})
                say('인스타 게시 성공', slot, link); ok = True; break
            except Exception as e:
                record({'slot': slot, 'platform': 'instagram', 'status': 'error', 'attempt': attempt, 'error': mask(e)})
                say('인스타 오류', slot, attempt, e)
                if attempt == 1:
                    time.sleep(45)
        if not ok:
            record({'slot': slot, 'platform': 'instagram', 'status': 'failed', 'note': '재시도 후 실패, 다음 회차로'})
        if ok and threads_on and item.get('threads_text'):
            th_id = None
            for attempt in (1, 2):
                try:
                    r = th_publish(item, urls)
                    if r:
                        th_id = r[0]
                        record({'slot': slot, 'platform': 'threads', 'status': 'success', 'media_id': r[0], 'permalink': r[1]})
                        say('쓰레드 게시 성공', slot, r[1])
                    break
                except Exception as e:
                    record({'slot': slot, 'platform': 'threads', 'status': 'error', 'attempt': attempt, 'error': mask(e)})
                    if attempt == 1:
                        time.sleep(45)
            if th_id and item.get('threads_reply'):  # 자기 댓글 (본 게시물 재시도와 분리 - 중복 게시 방지)
                for attempt in (1, 2):
                    try:
                        rid = th_reply(item, th_id)
                        record({'slot': slot, 'platform': 'threads_reply', 'status': 'success', 'media_id': rid, 'reply_to': th_id})
                        say('쓰레드 자기 댓글 성공', slot)
                        break
                    except Exception as e:
                        record({'slot': slot, 'platform': 'threads_reply', 'status': 'error', 'attempt': attempt, 'error': mask(e)})
                        if attempt == 1:
                            time.sleep(20)
        open(done, 'w').write('success' if ok else 'failed')
        commit_push([done, rfile], f'{"post" if ok else "fail"} {day} {slot}')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        say('치명적 오류:', e); sys.exit(1)
