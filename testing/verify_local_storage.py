"""Opt-in synthetic trial only; uploads two generated images and removes only those."""
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
from uuid import uuid4
from dotenv import dotenv_values
from flask import Flask
from PIL import Image
from supabase import create_client
from storage_media import browser_storage_url, install_storage_media


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('trial_directory', type=Path)
    args=parser.parse_args()
    if not (args.trial_directory/'SYNTHETIC-ONLY').is_file():
        raise SystemExit('Refusing a non-synthetic target')
    cfg=dotenv_values(args.trial_directory/'trial.env')
    upstream='http://127.0.0.1:55480'
    os.environ.update(LOCAL_STORAGE_PROXY='true', SUPABASE_URL=upstream)
    app=Flask(__name__);install_storage_media(app)
    client=app.test_client()
    storage=create_client(upstream,cfg['TRIAL_SERVICE_KEY']).storage
    suffix=uuid4().hex
    created=[]
    try:
        for bucket,fmt,mime,mode in [('book-covers','WEBP','image/webp','public'),
                                     ('board-uploads','PNG','image/png','sign')]:
            buffer=BytesIO();Image.new('RGB',(2,2),(120,35,40)).save(buffer,fmt)
            payload=buffer.getvalue();key=f'trial-media/{suffix}.{fmt.lower()}'
            storage.from_(bucket).upload(key,payload,{'content-type':mime})
            created.append((bucket,key))
            if mode=='public':
                remote=storage.from_(bucket).get_public_url(key)
            else:
                remote=storage.from_(bucket).create_signed_url(key,60)['signedURL']
            with app.test_request_context():
                local=browser_storage_url(remote)
            assert local.startswith('/media/storage/') and '127.0.0.1' not in local
            response=client.get(local)
            assert response.status_code==200 and response.data==payload
            assert response.mimetype==mime
            if mode=='sign':
                assert response.headers['Cache-Control']=='private, no-store'
                assert client.get(local.split('?',1)[0]).status_code==403
                assert client.get(local.split('?',1)[0]+'?token=invalid').status_code==404
        print(json.dumps({'passed':True,'real_storage_roundtrips':2,'public_private_isolation':True,'production_data_used':False}))
    finally:
        for bucket,key in created:
            storage.from_(bucket).remove([key])


if __name__=='__main__':
    main()
