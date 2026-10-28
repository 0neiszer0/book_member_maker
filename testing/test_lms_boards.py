import unittest
from io import BytesIO
from unittest.mock import patch
from flask import Flask, session
from PIL import Image
from boards import init_board_routes
from testing.test_lms_improvements import WriteDB


class Storage:
    def __init__(self):self.files={}
    def from_(self,bucket):assert bucket=='board-uploads';return self
    def upload(self,path,data,options):self.files[path]=data
    def remove(self,paths):
        for path in paths:self.files.pop(path,None)
    def create_signed_url(self,path,lifetime):return {'signedURL':'https://storage.invalid/signed/'+path}


class BoardUploadTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__);self.app.secret_key='fixture';self.app.config['TESTING']=True
        self.db=WriteDB({'boards':[dict(id='board',slug='general',board_type='general',is_active=True,read_role='member',write_role='member')]})
        self.db.storage=Storage()
        init_board_routes(self.app,self.db,lambda *a,**k:lambda f:f)
        self.client=self.app.test_client()
        with self.client.session_transaction() as state:state.update(user_id=1,user_role='member')

    def test_real_photo_and_rich_text_stored_together(self):
        photo=BytesIO();Image.new('RGB',(20,20),'red').save(photo,format='PNG');photo.seek(0)
        response=self.client.post('/board/general/write',data={'title':'사진 후기','content':'<p><strong>후기</strong></p><img src=x onerror=x>','content_format':'html','images':(photo,'photo.png')},content_type='multipart/form-data')
        self.assertEqual(response.status_code,302)
        post=self.db.rows['posts'][0];attachment=self.db.rows['post_attachments'][0]
        self.assertEqual(post['content'],'<p><strong>후기</strong></p>')
        self.assertEqual(attachment['mime_type'],'image/webp');self.assertEqual(attachment['post_id'],post['id'])
        self.assertEqual(len(self.db.storage.files),1)

    def test_invalid_photo_does_not_create_or_change_post(self):
        with patch('boards.render_template',return_value='form'):
            self.client.post('/board/general/write',data={'title':'사진 후기','content':'내용','images':(BytesIO(b'not an image'),'fake.png')},content_type='multipart/form-data')
        self.assertEqual(self.db.rows.get('posts',[]),[])
        self.assertEqual(self.db.storage.files,{})

    def test_five_attachment_limit_preserves_existing_post(self):
        self.db.rows['posts']=[dict(id='post',board_id='board',author_id=1,title='기존',content='기존 내용',deleted_at=None)]
        self.db.rows['post_attachments']=[dict(id=str(i),post_id='post',storage_path=str(i),display_order=i) for i in range(5)]
        with patch('boards.render_template',return_value='form'):
            self.client.post('/board/general/post/edit',data={'title':'변경','content':'변경 내용','images':(BytesIO(b'not an image'),'fake.png')},content_type='multipart/form-data')
        self.assertEqual(self.db.rows['posts'][0]['content'],'기존 내용')


if __name__=='__main__':unittest.main()
