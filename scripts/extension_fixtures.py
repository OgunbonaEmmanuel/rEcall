"""Explicit public image fixture download and synthetic DOCX generation; never run by the app."""
import io
import json
import zipfile
from xml.sax.saxutils import escape
import requests
from backend.config import ROOT

OUT=ROOT/'fixtures'/'generated'/'extensions'
SOURCES={
    'IMG_4821.jpg':('https://raw.githubusercontent.com/pytorch/hub/master/images/dog.jpg','a dog playing outside'),
    'IMG_5932.jpg':('https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/coco_sample.png','two cats resting on a couch'),
    'IMG_6104.jpg':('https://raw.githubusercontent.com/ultralytics/yolov5/master/data/images/bus.jpg','a bus parked on a city street'),
    'IMG_7785.jpg':('https://raw.githubusercontent.com/ultralytics/yolov5/master/data/images/zidane.jpg','two men wearing ties'),
}

def docx_bytes(body):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+body+'</w:body></w:document>')
    return stream.getvalue()

def paragraph(text,heading=False):
    style='<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' if heading else ''
    return '<w:p>'+style+'<w:r><w:t>'+escape(text)+'</w:t></w:r></w:p>'

def generate(download=False):
    OUT.mkdir(parents=True,exist_ok=True)
    if download:
        for name,(url,_) in SOURCES.items():
            if not (OUT/name).exists():
                response=requests.get(url,timeout=60)
                response.raise_for_status()
                (OUT/name).write_bytes(response.content)
    body=paragraph('Synthetic bicycle maintenance plan',True)+paragraph('Grease the bicycle chain every month. Contact Nora Bennett for a repair appointment.')
    body+='<w:tbl><w:tr><w:tc>'+paragraph('Brake service')+'</w:tc><w:tc>'+paragraph('$127.45')+'</w:tc></w:tr></w:tbl>'
    body+=paragraph('Safety checklist',True)+paragraph('Check tire pressure before a long ride.')
    body+=paragraph('<img src=x onerror=alert(1)> is untrusted source text.')
    path=OUT/'download_42.docx'
    path.write_bytes(docx_bytes(body))
    (OUT/'sources.json').write_text(json.dumps(SOURCES,indent=2),encoding='utf-8')
    return [OUT/name for name in SOURCES]+[path]

if __name__=='__main__':
    print('\n'.join(map(str,generate(download=True))))
