"""Deterministic synthetic files. No real personal data."""
from pathlib import Path
import json
import shutil
import pymupdf
from PIL import Image, ImageDraw, ImageFont
from backend.config import ROOT

OUT = ROOT / 'fixtures' / 'generated'
EXPECTED = [
    ('headphone receipt', 'IMG_4821.png', 1),
    ('89.99', 'IMG_4821.png', 1),
    ('proof I paid for wireless audio gear', 'IMG_4821.png', 1),
    ('Maya Chen', 'scan_023.pdf', 1),
    ('cancellation policy', 'download_7.pdf', 2),
    ('instructions for keeping my houseplants alive', 'Screenshot_108.png', 1),
    ('train to Bristol', 'ticket_09.jpg', 1),
    ('roasted tomato soup', 'image_110.jpeg', 1),
    ('internet bill', 'document_12.pdf', 1),
    ('appointment with the dentist', 'Screenshot_201.png', 1),
    ('library books due date', 'note_62.pdf', 1),
    ('IMG_4821.png', 'IMG_4821.png', 1),
]

def image_document(title, lines, color='#30594d'):
    image = Image.new('RGB', (1100, 1400), '#faf9f5')
    draw = ImageDraw.Draw(image)
    font_path = Path('C:/Windows/Fonts/arial.ttf')
    def font(size):
        return ImageFont.truetype(str(font_path), size) if font_path.exists() else ImageFont.load_default(size=size)
    draw.rectangle((0, 0, 1100, 25), fill=color)
    draw.text((85, 90), 'RECALL / SYNTHETIC DEMO', font=font(23), fill='#6a726b')
    draw.text((85, 210), title, font=font(48), fill=color)
    draw.line((85, 310, 1015, 310), fill='#d8ddd7', width=2)
    for i, line in enumerate(lines):
        draw.text((85, 380 + i * 85), line, font=font(32), fill='#25332e')
    draw.text((85, 1250), 'Made for testing. Not a real document.', font=font(23), fill='#7c837d')
    return image

def pdf(path, pages):
    with pymupdf.open() as doc:
        for title, lines in pages:
            page = doc.new_page(width=595, height=842)
            page.draw_rect((0, 0, 595, 15), fill=(.2, .35, .3), color=None)
            page.insert_text((50, 65), 'RECALL / SYNTHETIC DEMO', fontsize=10, color=(.4,.45,.4))
            page.insert_text((50, 125), title, fontsize=24, color=(.15,.3,.25))
            for i, line in enumerate(lines):
                page.insert_text((50, 200 + i*38), line, fontsize=14)
            page.insert_text((50, 780), 'Made for testing. Not a real document.', fontsize=10)
        doc.set_metadata({'producer':'Recall synthetic fixture', 'creationDate':'D:20260101000000'})
        doc.save(path, no_new_id=True)

def generate():
    OUT.mkdir(parents=True, exist_ok=True)
    names = ['IMG_4821.png','Screenshot_108.png','ticket_09.jpg','image_110.jpeg',
             'Screenshot_201.png','IMG_0000.png','scan_023.pdf','download_7.pdf','document_12.pdf','note_62.pdf']
    if all((OUT / name).exists() for name in names):
        return [OUT / name for name in names]
    image_document('SOUND & CO.', ['Sales receipt #RC-4821','Wireless headphones','Quantity: 1','Total paid: $89.99','Paid by card on 12 June 2026','Thank you for your purchase.']).save(OUT / names[0])
    image_document('Plant care notes', ['Monstera and pothos care','Water when the top soil feels dry.','Keep plants in bright indirect light.','Feed once a month during spring.'], '#536d37').save(OUT / names[1])
    image_document('Rail booking', ['Passenger: Alex Taylor','Train to Bristol Temple Meads','From: London Paddington','Departure: 09:30, 18 July 2026','Seat 24A - Coach B'], '#394e76').save(OUT / names[2])
    image_document('Roasted tomato soup', ['Ingredients: tomatoes, garlic, basil','Roast vegetables for 30 minutes.','Blend with vegetable stock.','Serve warm with crusty bread.'], '#994d35').save(OUT / names[3])
    image_document('Dental appointment', ['Cedar Dental Clinic','Routine checkup and cleaning','Appointment: 14 August at 10:00','Please arrive 10 minutes early.'], '#476a85').save(OUT / names[4])
    blank = Image.new('RGB', (900,700), '#e8dfd0')
    draw = ImageDraw.Draw(blank)
    draw.ellipse((210,120,690,590), fill='#799487')
    draw.rectangle((400,50,500,650), fill='#d6b274')
    blank.save(OUT / names[5])
    scan = image_document('Community workshop', ['Contact: Maya Chen','Saturday pottery workshop','Date: 21 September 2026','Venue: Riverside Art Studio','Bring an apron and a packed lunch.'], '#775b82')
    import io
    buf = io.BytesIO()
    scan.save(buf, format='PNG')
    with pymupdf.open() as doc:
        page = doc.new_page(width=550, height=700)
        page.insert_image(page.rect, stream=buf.getvalue())
        doc.save(OUT / names[6], no_new_id=True)
    pdf(OUT / names[7], [('Stay confirmation', ['Harbour House Guest Rooms','Guest: Alex Taylor','Check-in: 20 October 2026','Booking reference: HH-2046']),
                        ('Cancellation policy', ['Cancel at least 48 hours before arrival.','Late cancellations incur a one-night charge.','Contact the front desk to change your stay.'])])
    pdf(OUT / names[8], [('Internet bill', ['Provider: ClearWave Broadband','Fibre internet - September 2026','Total due: $54.50','Payment due: 30 September 2026'])])
    pdf(OUT / names[9], [('Library borrowing slip', ['Oak Street Library','Borrowed: The Secret Garden','Borrowed: A Brief History of Time','Books due back: 8 November 2026'])])
    (OUT / 'expected.json').write_text(json.dumps(EXPECTED, indent=2), encoding='utf-8')
    shutil.copyfile(OUT / names[0], OUT / 'duplicate_receipt.png')
    return [OUT / name for name in names]

if __name__ == '__main__':
    print('\n'.join(str(p) for p in generate()))
