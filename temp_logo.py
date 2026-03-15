import urllib.request, re
try:
    html = urllib.request.urlopen('https://www.uwc.org/').read().decode('utf-8')
    m = re.search(r'https://[^"]*logo[^"]*\.(?:png|svg)', html)
    print(m.group(0) if m else 'NOT FOUND')
except Exception as e:
    print("Error:", e)
