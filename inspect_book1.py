from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

path = Path('Book1.xlsx')
print('exists', path.exists())
with zipfile.ZipFile(path, 'r') as z:
    names = z.namelist()
    for name in names:
        if name in ('xl/workbook.xml', 'xl/sharedStrings.xml') or name.startswith('xl/worksheets/'):
            print(name)
    if 'xl/workbook.xml' in names:
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        sheets = wb.findall('.//ns:sheets/ns:sheet', ns)
        print('sheets', [s.attrib.get('name') for s in sheets])
    if 'xl/sharedStrings.xml' in names:
        ss = ET.fromstring(z.read('xl/sharedStrings.xml'))
        strings = ["".join(t.text or '' for t in si.findall('.//ns:t', {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'})) for si in ss.findall('.//ns:si', {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'})]
        print('shared count', len(strings))
    # print first 20 cells of first worksheet
    sheet_files = [n for n in names if n.startswith('xl/worksheets/')]
    if sheet_files:
        data = z.read(sheet_files[0])
        ws = ET.fromstring(data)
        ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        rows = ws.findall('.//ns:row', ns)
        for idx, row in enumerate(rows[:20], 1):
            cells = []
            for c in row.findall('ns:c', ns):
                ref = c.attrib.get('r')
                t = c.attrib.get('t')
                v = c.find('ns:v', ns)
                value = v.text if v is not None else ''
                if t == 's':
                    value = strings[int(value)]
                cells.append((ref, value))
            print(idx, cells)
