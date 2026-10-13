# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure tray wire/state/identity/alpha regressions; never broadcasts or posts Win32 messages."""
import base64
from pathlib import Path
import struct
import sys
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import notification_pixels as pixels, notification_protocol as tray

IDENTITY = (11, 22, '333', 'BLUI_QA_NotifyIcon')


def packet(message=0, *, handle=100, uid=17, flags=7, callback=0x8001, icon=200, tip='Test Icon', version=0, guid=''):
    data = bytearray(964)
    struct.pack_into('<8I', data, 0, 0, message, 956, handle, uid, flags, callback, icon)
    encoded = (tip + '\x00').encode('utf-16-le')
    data[32:32 + min(len(encoded), 256)] = encoded[:256]
    struct.pack_into('<I', data, 808, version)
    if guid:
        data[944:960] = uuid.UUID(guid).bytes_le
    return bytes(data)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.identity = mock.Mock(return_value=IDENTITY)
        self.raster = mock.Mock(return_value=(1, 1, base64.b64encode(b'\xff\x00\x00\xff').decode('ascii')))
        self.store = tray.Store(self.identity, self.raster)
        self.add = tray.parse(packet())

    def test_full_cross_arch_wire_offsets(self):
        guid = '12345678-1234-5678-90ab-123456789abc'
        value = tray.parse(packet(flags=7 | tray.NIF_GUID, guid=guid, version=4))
        self.assertEqual((value['handle'], value['uid'], value['callback'], value['icon']), (100, 17, 0x8001, 200))
        self.assertEqual(value['tip'], 'Test Icon')
        self.assertEqual(value['guid'], guid)
        self.assertEqual(value['version'], 4)
        self.assertEqual(tray.key(value), 'guid:' + guid)

    def test_malformed_truncated_callback_and_message_rejected(self):
        for value in (b'', packet()[:31], b'x' * 4097, packet(message=99), packet(callback=0x10),
                      packet(flags=tray.NIF_GUID)[:100], packet()[:40], packet(4)[:100]):
            with self.assertRaises(ValueError):
                tray.parse(value)

    def test_add_modify_state_delete_and_version(self):
        self.assertTrue(self.store.apply(self.add))
        row = self.store.snapshot()[0]
        self.assertEqual(row['tip'], 'Test Icon')
        self.assertEqual(row['pid'], 11)
        modify = tray.parse(packet(1, flags=tray.NIF_TIP, tip='Updated'))
        self.assertTrue(self.store.apply(modify))
        self.assertEqual(self.store.snapshot()[0]['tip'], 'Updated')
        self.assertEqual(self.raster.call_count, 1, 'TIP update must not re-decode pixels')
        self.assertTrue(self.store.apply(tray.parse(packet(4, flags=0, version=4))))
        self.assertEqual(self.store.snapshot()[0]['version'], 4)
        self.assertTrue(self.store.apply(tray.parse(packet(2, flags=0))))
        self.assertEqual(self.store.snapshot(), [])

    def test_hidden_state_mask_only_changes_requested_bit(self):
        self.store.apply(self.add)
        modify = tray.parse(packet(1, flags=tray.NIF_STATE))
        modify['state'], modify['state_mask'] = 1, 1
        self.store.apply(modify)
        self.assertTrue(self.store.snapshot()[0]['hidden'])
        modify['state'], modify['state_mask'] = 0, 2
        self.store.apply(modify)
        self.assertTrue(self.store.snapshot()[0]['hidden'])

    def test_invalid_or_changed_owner_is_not_adopted(self):
        self.identity.return_value = None
        self.assertFalse(self.store.apply(self.add))
        self.identity.side_effect = [IDENTITY, (11, 22, 'reused', IDENTITY[3])]
        self.assertFalse(self.store.apply(self.add))
        self.assertEqual(self.store.snapshot(), [])

    def test_guid_add_can_restore_same_app_new_owner_but_modify_cannot(self):
        guid = '12345678-1234-5678-90ab-123456789abc'
        first = tray.parse(packet(flags=7 | tray.NIF_GUID, guid=guid))
        self.store.apply(first)
        self.identity.return_value = (12, 22, 'restart', IDENTITY[3])
        self.assertFalse(self.store.apply(tray.parse(packet(1, flags=7 | tray.NIF_GUID, guid=guid))))
        self.assertTrue(self.store.apply(first))
        self.assertEqual(self.store.snapshot()[0]['pid'], 12)

    def test_stale_and_dead_icon_pruned_without_callback(self):
        self.store.apply(self.add)
        self.identity.return_value = None
        self.store.prune()
        self.assertEqual(self.store.snapshot(), [])

    def test_legacy_click_uses_uid_and_unpacked_mouse_messages(self):
        self.store.apply(self.add)
        row = self.store.rows[tray.key(self.add)]
        self.assertEqual(tray.callback_messages(row, 'LEFT', 10, 20), [(17, 0x201), (17, 0x202)])
        self.assertEqual(tray.callback_messages(row, 'RIGHT', 10, 20), [(17, 0x204), (17, 0x205)])

    def test_version4_packs_negative_monitor_coords_uid_and_context(self):
        self.store.apply(self.add)
        row = self.store.rows[tray.key(self.add)]
        row['version'] = 4
        messages = tray.callback_messages(row, 'RIGHT', -1920, -30)
        self.assertEqual(messages[-1][1], (17 << 16) | 0x7b)
        self.assertEqual(messages[-1][0] & 0xffff, (-1920 & 0xffff))
        self.assertEqual(messages[-1][0] >> 16, (-30 & 0xffff))
        self.assertEqual(tray.callback_messages(row, 'HOVER_ENTER', 10, 20)[-1][1] & 0xffff, 0x406)
        self.assertEqual(tray.callback_messages(row, 'HOVER_LEAVE', 10, 20)[-1][1] & 0xffff, 0x407)

    def test_action_revalidates_between_each_callback(self):
        self.store.apply(self.add)
        post = mock.Mock(return_value=True)
        foreground = mock.Mock()
        self.identity.side_effect = [IDENTITY, IDENTITY, None]
        with self.assertRaises(ValueError):
            self.store.action(tray.key(self.add), 'LEFT', 10, 20, post, foreground)
        self.assertEqual(post.call_count, 1)
        foreground.assert_called_once_with(11)

    def test_unknown_key_event_or_anchor_never_sends_callback(self):
        self.store.apply(self.add)
        post, foreground = mock.Mock(), mock.Mock()
        for key, event, x, y in (('arbitrary', 'LEFT', 1, 2), (tray.key(self.add), 'CLOSE_APP', 1, 2),
                                 (tray.key(self.add), 'LEFT', True, 2), (tray.key(self.add), 'LEFT', 32768, 2)):
            with self.assertRaises(ValueError):
                self.store.action(key, event, x, y, post, foreground)
        post.assert_not_called()
        foreground.assert_not_called()

    def test_row_budget_is_bounded(self):
        for uid in range(tray.MAX_ICONS + 1):
            self.store.apply(tray.parse(packet(uid=uid)))
        self.assertEqual(len(self.store.rows), tray.MAX_ICONS)

    def test_setversion_without_valid_icon_or_unsupported_fails(self):
        self.assertFalse(self.store.apply(tray.parse(packet(4, flags=0, version=4))))
        self.store.apply(self.add)
        self.assertFalse(self.store.apply(tray.parse(packet(4, flags=0, version=99))))

    def test_mask_and_premultiplied_pixel_recovery(self):
        # Transparent, opaque red, half-alpha red. DIB memory is BGRA, output RGBA.
        black = bytes((0, 0, 0, 0, 0, 0, 255, 255, 0, 0, 128, 128))
        white = bytes((255, 255, 255, 0, 0, 0, 255, 255, 127, 127, 255, 128))
        self.assertEqual(pixels.rgba_from_composites(black, white),
                         bytes((0, 0, 0, 0, 255, 0, 0, 255, 255, 0, 0, 128)))


if __name__ == '__main__':
    unittest.main()
