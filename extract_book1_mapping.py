from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

path = Path('Book1.xlsx')
if not path.exists():
    raise FileNotFoundError(path)

with zipfile.ZipFile(path, 'r') as z:
    shared = None
    if 'xl/sharedStrings.xml' in z.namelist():
        ss = ET.fromstring(z.read('xl/sharedStrings.xml'))
        ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        shared = ["".join(t.text or '' for t in si.findall('.//ns:t', ns)) for si in ss.findall('.//ns:si', ns)]
    ws = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    rows = ws.findall('.//ns:row', ns)
    mapping = {}
    for row in rows[3:]:
        cells = {}
        for c in row.findall('ns:c', ns):
            ref = c.attrib.get('r')
            v = c.find('ns:v', ns)
            if v is None:
                continue
            value = v.text
            if c.attrib.get('t') == 's':
                value = shared[int(value)]
            cells[ref] = value.strip() if value else ''
        b = cells.get('B', '').strip()
        d = cells.get('D', '').strip()
        if b:
            mapping.setdefault(b, []).append(d)

for key in mapping:
    values = [v for v in mapping[key] if v]
    print(f'"{key}": {values}')
