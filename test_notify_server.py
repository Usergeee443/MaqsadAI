#!/usr/bin/env python3
"""
Payment Notify Server test skripti
Mini ilovadan keladigan so'rovlarni simulyatsiya qiladi
"""

import requests
import json
import sys

def test_server():
    """Server ni to'liq test qilish"""
    print("🧪 Payment Notify Server Test")
    print("=" * 50)
    
    base_url = "http://localhost:5005"
    
    # 1. Health check
    print("\n1️⃣ Health Check Test...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        print(f"   ✅ Status: {response.status_code}")
        print(f"   📄 Response: {response.json()}")
    except requests.exceptions.ConnectionError:
        print("   ❌ Server ulanay olmadi! Server ishga tushurilganmi?")
        print("   💡 Ishga tushiring: python3 payment_notify_server.py")
        return False
    except Exception as e:
        print(f"   ❌ Xatolik: {e}")
        return False
    
    # 2. Success payment test
    print("\n2️⃣ Muvaffaqiyatli to'lov testi...")
    test_data_success = {
        "user_id": 6429299277,  # Admin ID
        "amount": 29990,
        "status": "success"
    }
    print(f"   📤 Ma'lumotlar: {json.dumps(test_data_success, indent=2)}")
    try:
        response = requests.post(
            f"{base_url}/payment-notify",
            json=test_data_success,
            timeout=10
        )
        print(f"   ✅ Status: {response.status_code}")
        print(f"   📄 Response: {response.json()}")
    except Exception as e:
        print(f"   ❌ Xatolik: {e}")
    
    # 3. Failed payment test
    print("\n3️⃣ Xatolik to'lov testi...")
    test_data_failed = {
        "user_id": 6429299277,
        "amount": 29990,
        "status": "failed"
    }
    print(f"   📤 Ma'lumotlar: {json.dumps(test_data_failed, indent=2)}")
    try:
        response = requests.post(
            f"{base_url}/payment-notify",
            json=test_data_failed,
            timeout=10
        )
        print(f"   ✅ Status: {response.status_code}")
        print(f"   📄 Response: {response.json()}")
    except Exception as e:
        print(f"   ❌ Xatolik: {e}")
    
    # 4. Invalid request test
    print("\n4️⃣ Noto'g'ri so'rov testi...")
    test_data_invalid = {
        "user_id": 6429299277,
        "amount": 29990
        # status yo'q!
    }
    print(f"   📤 Ma'lumotlar: {json.dumps(test_data_invalid, indent=2)}")
    try:
        response = requests.post(
            f"{base_url}/payment-notify",
            json=test_data_invalid,
            timeout=10
        )
        print(f"   ⚠️  Status: {response.status_code} (kutilgan 400)")
        print(f"   📄 Response: {response.json()}")
    except Exception as e:
        print(f"   ❌ Xatolik: {e}")
    
    print("\n" + "=" * 50)
    print("✅ Barcha testlar yakunlandi!")
    print("\n💡 Eslatma: Bot botingizga xabar yuborilganini tekshiring!")
    return True

if __name__ == '__main__':
    success = test_server()
    sys.exit(0 if success else 1)

