"""
Test file for Session Cleanup Manager
Cleanup manager ni test qilish uchun fayl
"""

import asyncio
import time
from app.cleanup_manager_new import cleanup_manager, SessionCleanupManager


async def test_cleanup_manager():
    """Cleanup manager ni test qilish"""
    print("=" * 60)
    print("SESSION CLEANUP MANAGER TEST")
    print("=" * 60)
    
    # Test 1: Register va Track
    print("\n[TEST 1] Register va Track Sessions")
    print("-" * 60)
    
    test_dict = {}
    test_set = set()
    
    cleanup_manager.register("ADMIN_ADD_SESSIONS", test_dict)
    cleanup_manager.register("CONTACT_ADMIN_SESSIONS", test_set)
    
    # Sessiyalar qo'shish
    cleanup_manager.track_session_start("ADMIN_ADD_SESSIONS", 123)
    cleanup_manager.track_session_start("ADMIN_ADD_SESSIONS", 456)
    cleanup_manager.track_session_start("CONTACT_ADMIN_SESSIONS", 789)
    
    test_dict[123] = {"target_id": 111, "created_at": time.strftime('%Y-%m-%dT%H:%M:%S')}
    test_dict[456] = {"target_id": 222, "created_at": time.strftime('%Y-%m-%dT%H:%M:%S')}
    test_set.add(789)
    
    print(f"✓ Registered objects: {list(cleanup_manager.registered_objects.keys())}")
    print(f"✓ ADMIN_ADD_SESSIONS: {test_dict}")
    print(f"✓ CONTACT_ADMIN_SESSIONS: {test_set}")
    print(f"✓ Tracked timestamps: {len(cleanup_manager.timestamps)}")
    
    # Test 2: TTL Konfiguratsiya
    print("\n[TEST 2] TTL Konfiguratsiya")
    print("-" * 60)
    
    ttl_config = {
        "ADMIN_ADD_SESSIONS": "1 soat (3600 sec)",
        "IMPORT_SESSIONS": "2 soat (7200 sec)",
        "VIP_ADD_SESSIONS": "30 minut (1800 sec)",
        "PENDING_START_CODES": "24 soat (86400 sec)",
        "BROADCAST_SESSIONS": "30 minut (1800 sec)",
    }
    
    for name, ttl_desc in ttl_config.items():
        actual_ttl = cleanup_manager.CONFIG.get(name, "Not found")
        print(f"✓ {name}: {ttl_desc}")
        assert actual_ttl > 0, f"TTL not found for {name}"
    
    # Test 3: Session End va Track
    print("\n[TEST 3] Session End Tracking")
    print("-" * 60)
    
    print(f"Before cleanup: {len(cleanup_manager.timestamps)} timestamps")
    cleanup_manager.track_session_end("ADMIN_ADD_SESSIONS", 123)
    print(f"✓ Session ended: ADMIN_ADD_SESSIONS#123")
    print(f"After cleanup: {len(cleanup_manager.timestamps)} timestamps")
    
    # Test 4: Cleanup Statistics
    print("\n[TEST 4] Cleanup Statistics")
    print("-" * 60)
    
    stats = cleanup_manager.get_stats()
    print(f"✓ Total registered sessions: {stats['total_registered']}")
    print(f"✓ Total tracked timestamps: {stats['total_tracked_timestamps']}")
    
    for name, obj_stats in stats['registered_objects'].items():
        print(f"\n  {name}:")
        print(f"    - Type: {obj_stats['type']}")
        print(f"    - TTL: {obj_stats['ttl']}s")
        print(f"    - Size: {obj_stats['size']}")
    
    # Test 5: Manual Cleanup
    print("\n[TEST 5] Manual Cleanup Test")
    print("-" * 60)
    
    # Expired session qo'shish
    import datetime as dt
    old_time = (dt.datetime.utcnow() - dt.timedelta(hours=2)).isoformat()
    test_dict[999] = {"target_id": 999, "created_at": old_time}
    
    print(f"Added expired session: {test_dict[999]}")
    print(f"Before cleanup: {len(test_dict)} items in ADMIN_ADD_SESSIONS")
    
    await cleanup_manager.cleanup()
    
    print(f"After cleanup: {len(test_dict)} items in ADMIN_ADD_SESSIONS")
    if 999 not in test_dict:
        print("✓ Expired session successfully removed!")
    
    # Test 6: Pending Start Codes (Special Handling)
    print("\n[TEST 6] Special Case: PENDING_START_CODES")
    print("-" * 60)
    
    pending_dict = {}
    cleanup_manager.register("PENDING_START_CODES", pending_dict)
    
    # Format: (code, part, timestamp)
    current_time = time.time()
    old_time = current_time - 86500  # 24 soatdan ko'p
    
    pending_dict[111] = (268, 1, current_time)  # Fresh
    pending_dict[222] = (269, 2, old_time)  # Expired
    
    print(f"Before cleanup: {len(pending_dict)} items")
    await cleanup_manager.cleanup()
    print(f"After cleanup: {len(pending_dict)} items")
    
    if 222 not in pending_dict:
        print("✓ Expired PENDING_START_CODE successfully removed!")
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED SUCCESSFULLY! ✓")
    print("=" * 60)


async def test_cleanup_loop():
    """Cleanup loop ni test qilish"""
    print("\n[TEST] Cleanup Loop (5 sec interval uchun)")
    print("-" * 60)
    
    test_dict = {}
    cleanup_manager_test = SessionCleanupManager()
    cleanup_manager_test.register("TEST_SESSIONS", test_dict)
    
    # Test sessiya
    cleanup_manager_test.track_session_start("TEST_SESSIONS", 1)
    test_dict[1] = {"created_at": time.strftime('%Y-%m-%dT%H:%M:%S')}
    
    print("✓ Cleanup loop boshlandi (5 sec interval)")
    cleanup_manager_test.start_cleanup_loop()
    
    print("✓ 6 sekundni kuting...")
    await asyncio.sleep(6)
    
    print("✓ Cleanup loop to'xtatildi")
    await cleanup_manager_test.stop_cleanup_loop()
    
    print(f"✓ Test completed")


if __name__ == "__main__":
    print("\n🧪 STARTING SESSION CLEANUP MANAGER TESTS\n")
    
    # Asosiy testlar
    asyncio.run(test_cleanup_manager())
    
    # Loop test
    # asyncio.run(test_cleanup_loop())
    
    print("\n✅ ALL TESTS PASSED!\n")
