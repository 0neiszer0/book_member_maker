"""Focused live check against ONLY the explicitly started loopback preview.
Edits one document in the separate integration copy, then restores its text.
"""
from urllib.parse import quote, urlsplit
import requests
from bs4 import BeautifulSoup

BASE='http://127.0.0.1:5105'
DOC='학기 기록 작성 양식'


def client(member):
    s=requests.Session();s.trust_env=False
    page=s.get(BASE+'/__wiki_preview',timeout=20)
    csrf=BeautifulSoup(page.text,'html.parser').select_one('input[name=csrf]')['value']
    result=s.post(BASE+'/__wiki_preview',data={'csrf':csrf,'member':str(member)},headers={'Origin':BASE},timeout=30)
    assert result.status_code==200
    return s


def editor(s):
    result=s.get(BASE+'/wiki/edit/'+quote(DOC),timeout=30)
    assert result.status_code==200, result.status_code
    soup=BeautifulSoup(result.text,'html.parser')
    return {'wiki_csrf':soup.select_one('input[name=wiki_csrf]')['value'],
            'version':soup.select_one('input[name=version]')['value'],
            'content':soup.select_one('textarea[name=content]').get_text(),
            'summary':'로컬 연동 확인', 'action':'save'}


def submit(s, form):
    return s.post(BASE+'/wiki/edit/'+quote(DOC),data=form,headers={'Origin':BASE},timeout=30,allow_redirects=False)


if __name__=='__main__':
    s=client(1)
    original=editor(s)
    changed=dict(original,content=original['content']+'\n\n로컬 저장 검증 문장입니다.\n')
    preview=submit(s,dict(changed,action='preview'))
    assert preview.status_code==200 and '미리보기' in preview.text
    assert editor(s)['version']==original['version'], 'Preview modified history'
    result=submit(s,changed)
    assert result.status_code==303, (result.status_code,BeautifulSoup(result.text,'html.parser').get_text()[-600:])
    assert editor(s)['content']==changed['content']
    stale=submit(s,dict(original,content='이 오래된 편집은 저장되면 안 됩니다.'))
    assert stale.status_code==409 and '이 오래된 편집은 저장되면 안 됩니다.' in stale.text
    current=editor(s)
    assert current['content']==changed['content']
    restored=submit(s,dict(current,content=original['content'],summary='로컬 검증 후 원문 복원'))
    assert restored.status_code==303 and editor(s)['content']==original['content']
    history=s.get(BASE+'/wiki/history/'+quote(DOC),timeout=30)
    assert history.status_code==200 and 'member-' in history.text
    read_only=client(2)
    assert read_only.get(BASE+'/wiki/w/'+quote(DOC),timeout=30).status_code==200
    assert read_only.get(BASE+'/wiki/edit/'+quote(DOC),timeout=30).status_code==403
    assert submit(read_only,original).status_code==403
    print('PASS: native preview, save, author/history, stale-version 409 with draft, restore, resting-member read-only')
