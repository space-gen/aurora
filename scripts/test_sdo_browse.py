import requests
import re
import datetime

def test_browse_listing():
    # Use yesterday to ensure files are fully uploaded
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    y, m, d = yesterday.strftime("%Y"), yesterday.strftime("%m"), yesterday.strftime("%d")
    url = f"https://sdo.gsfc.nasa.gov/assets/img/browse/{y}/{m}/{d}/"
    
    print(f"Fetching: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            # Find all .jpg files
            jpgs = re.findall(r'href="([^"]+\.jpg)"', r.text)
            print(f"Found {len(jpgs)} JPG files.")
            if jpgs:
                print("Samples:")
                for j in jpgs[:5]:
                    print(f"  {url}{j}")
        else:
            print("Failed to get listing.")
    except Exception as e:
        print(f"Error: {e}")

def test_helioviewer():
    # SDO/AIA 171 is sourceId 10
    url = "https://api.helioviewer.org/v2/getClosestImage/?date=2024-05-20T12:00:00Z&sourceId=10"
    print(f"Fetching from Helioviewer: {url}")
    try:
        r = requests.get(url, timeout=20)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print("JSON Result:")
            print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    import json
    test_helioviewer()
