import requests
import datetime

def test_sdo_url():
    # AIA 171 for 2024-01-01 00:00:00
    url = "https://sdo.gsfc.nasa.gov/assets/img/browse/2024/01/01/20240101_000000_1024_0171.jpg"
    print(f"Testing URL: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        r = requests.head(url, headers=headers, timeout=10)
        print(f"Status Code: {r.status_code}")
        if r.status_code == 200:
            print("URL is VALID!")
        else:
            print("URL is INVALID.")
    except Exception as e:
        print(f"Error: {e}")

def test_soho_url():
    url = "https://soho.nascom.nasa.gov/data/REaltime/data/2024/01/01/20240101_0000_c2_1024.jpg"
    print(f"Testing SOHO URL: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        r = requests.head(url, headers=headers, timeout=10)
        print(f"Status Code: {r.status_code}")
        if r.status_code == 200:
            print("SOHO URL is VALID!")
        else:
            print("SOHO URL is INVALID.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # test_sdo_url()
    test_soho_url()
