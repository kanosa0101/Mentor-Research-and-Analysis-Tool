"""Push acceptance tests: temporary databases and fake delivery only."""
import base64
import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from crawler import push_util as push
from crawler import opportunity_util as util


DAY = date(2026, 11, 15)


def subscription(endpoint='https://fcm.googleapis.com/fcm/send/test-device'):
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
    return {'endpoint': endpoint, 'keys': {'auth': encode(b'a' * 16),
            'p256dh': encode(b'\x04' + b'b' * 64)}, 'expirationTime': None}


def activity(**changes):
    item = dict(id='test-camp', title='计算机冬令营', school_name='测试大学', unit='计算机学院',
                kind='winter_camp', graduation_year=2028, source_state='verified', cycle='current',
                source_url='https://example.edu.cn/camp', checked_at=DAY.isoformat(),
                verified_at=DAY.isoformat(), eligibility=['2028届计算机相关专业本科生'],
                materials=['简历'], deadline='2026-11-25', deadline_note='',
                registration_start='2026-11-01', event_end='', application_url='',
                application_method='按官方要求申请', contact='官方联系人', research_directions=[])
    item.update(changes)
    item['content_classification'] = dict(scope='institutional_activity', organizer_level='school_department',
        organizer_name=item['unit'], source_url=item['source_url'], quote='测试大学计算机学院统一冬令营', verified_at='2026-11-15')
    return item


class PushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='push-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        # Any accidental production sender use is a test failure, not an external request.
        self.guard = patch.object(push, 'send', side_effect=AssertionError('real push prohibited'))
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def register(self, endpoint=None, **filters):
        values = dict(school='', kind='', year='', query='', discoveries=False)
        values.update(filters)
        return push.subscribe(self.root, {'subscription': subscription(endpoint) if endpoint else subscription(),
                                         'filters': values})

    def record(self, *items, day=DAY, monitoring=None):
        # Dispatch rechecks the current public catalog, not only a queued event's old label.
        records = []
        for item in items:
            complete = {key: '' for key in util.TEXT}
            complete.update({key: None for key in util.YEARS})
            complete.update({key: [] for key in util.LISTS})
            complete.update({key: value for key, value in item.items() if key in util.TEXT | util.YEARS | util.LISTS | util.OPTIONAL})
            complete['evidence'] = ['测试学院统一组织活动']
            records.append(complete)
        (self.root / 'data').mkdir(exist_ok=True)
        (self.root / 'data/opportunities.json').write_text(json.dumps({'version': 1, 'opportunities': records}), encoding='utf-8')
        return push.record(self.root, {'opportunities': list(items)}, monitoring=monitoring, day=day)

    def sender(self, sub, payload):
        self.calls.append((sub, payload))
        return 201

    def publish(self, **changes):
        self.record()
        self.record(activity(**changes))

    def test_explicit_subscribe_owned_update_and_unsubscribe(self):
        self.publish()
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 0)
        owner = self.register()
        with push.database(self.root) as db:
            stored = db.execute('SELECT * FROM subscriptions').fetchone()
        self.assertEqual(stored['token'], hashlib.sha256(owner['token'].encode()).hexdigest())
        self.assertNotEqual(stored['token'], owner['token'])
        with self.assertRaises(ValueError):
            self.register(query='hijack')
        body = dict(subscription=subscription(), filters=dict(school='', kind='', year='', query='计算机', discoveries=False),
                    token=owner['token'])
        self.assertEqual(push.subscribe(self.root, body), owner)
        for invalid in ({'id': owner['id']}, dict(owner, token='x' * 43)):
            with self.assertRaises(ValueError):
                push.unsubscribe(self.root, invalid)
        push.unsubscribe(self.root, owner)
        with push.database(self.root) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0], 0)

    def test_endpoint_allowlist_rejects_ssrf_and_host_spoofing(self):
        for endpoint in ('http://fcm.googleapis.com/a', 'https://127.0.0.1/a',
                         'https://fcm.googleapis.com.evil.test/a', 'https://evil.test/fcm.googleapis.com',
                         'https://fcm.googleapis.com:444/a', 'https://user@fcm.googleapis.com/a',
                         'https://fcm.googleapis.com/a#fragment', 'https://notify.windows.com.evil.test/a'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                push.validate_subscription(subscription(endpoint))
        for endpoint in ('https://updates.push.services.mozilla.com/wpush/a',
                         'https://web.push.apple.com/a', 'https://wns2.notify.windows.com/a'):
            push.validate_subscription(subscription(endpoint))

    def test_initial_baseline_does_not_send_existing_items_or_deadlines(self):
        self.register()
        self.assertEqual(self.record(activity(deadline='2026-11-18')), 0)
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 0)
        self.assertEqual(push.recent(self.root), [])

    def test_new_subscriber_does_not_receive_existing_events(self):
        self.publish()
        self.register()
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 0)
        self.assertEqual(self.calls, [])

    def test_published_changed_and_deadline_events_are_deduplicated(self):
        self.record()
        self.register()
        item = activity()
        self.assertEqual(self.record(item), 1)
        self.assertEqual(self.record(item), 0)
        item['materials'].append('成绩单')
        self.assertEqual(self.record(item), 1)
        self.assertEqual(self.record(item), 0)
        self.assertEqual(self.record(item, day=DAY + timedelta(days=7)), 1)
        self.assertEqual(self.record(item, day=DAY + timedelta(days=7)), 0)
        events = push.recent(self.root)
        self.assertEqual({e['kind'] for e in events}, {'published', 'changed', 'deadline'})
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 3)
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 0)
        self.assertEqual(len(self.calls), 3)

    def test_verified_publication_after_unverified_discovery_emits_once(self):
        self.record(activity(source_state='unavailable'))
        self.register()
        self.assertEqual(self.record(activity()), 1)
        self.assertEqual(self.record(activity()), 0)
        self.assertEqual(push.recent(self.root)[0]['kind'], 'published')

    def test_only_matching_subscribers_receive_public_events(self):
        self.record()
        self.register(school='测试大学', kind='winter_camp', year='2028', query='计算机')
        self.register('https://fcm.googleapis.com/fcm/send/wrong-school', school='别的学校')
        self.register('https://fcm.googleapis.com/fcm/send/wrong-kind', kind='summer_camp')
        self.register('https://fcm.googleapis.com/fcm/send/wrong-year', year='2027')
        self.register('https://fcm.googleapis.com/fcm/send/wrong-query', query='不存在方向')
        self.record(activity())
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 1)
        self.assertTrue(self.calls[0][0]['endpoint'].endswith('test-device'))

    def test_unclassified_discoveries_do_not_broadcast_even_when_opted_in(self):
        old = dict(id='old', url='https://example.edu.cn/old', title='旧冬令营', unit='计算机学院',
                   discovery_status='discovered_later', publication_date='2025-11-01')
        self.record(monitoring={'candidates': [old]})
        self.register()
        self.register('https://fcm.googleapis.com/fcm/send/discoveries', discoveries=True)
        new = dict(old, id='new', url='https://example.edu.cn/new', title='新冬令营', publication_date='2026-11-15')
        self.assertEqual(self.record(monitoring={'candidates': [old, new]}), 0)
        self.assertEqual(self.record(monitoring={'candidates': [old, new]}), 0)
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 0)
        self.assertEqual(self.calls, [])

    def test_failed_delivery_retries_and_success_stops_retries(self):
        self.record()
        self.register()
        self.record(activity())
        self.assertEqual(push.dispatch(self.root, lambda *_: 503)['failed'], 1)
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 1)
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 0)
        with push.database(self.root) as db:
            self.assertEqual(tuple(db.execute('SELECT attempts,sent FROM deliveries').fetchone()), (2, 1))

    def test_retries_are_bounded_and_expired_subscription_is_deleted(self):
        self.record()
        self.register()
        self.record(activity())
        for _ in range(5):
            self.assertEqual(push.dispatch(self.root, lambda *_: 503)['failed'], 1)
        self.assertEqual(push.dispatch(self.root, lambda *_: 503)['failed'], 0)
        self.register('https://fcm.googleapis.com/fcm/send/expired')
        self.record(activity(materials=['新材料']))
        self.assertEqual(push.dispatch(self.root, lambda *_: 410)['expired'], 2)
        with push.database(self.root) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0], 0)

    def test_unsubscribe_before_dispatch_cancels_pending_delivery(self):
        self.record()
        owner = self.register()
        self.record(activity())
        push.unsubscribe(self.root, owner)
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 0)
        self.assertFalse(self.calls)

    def test_unsubscribe_during_dispatch_stops_remaining_events(self):
        self.record()
        owner = self.register()
        self.record(activity())
        self.record(activity(materials=['更新材料']))
        def sender(sub, payload):
            self.calls.append(payload)
            push.unsubscribe(self.root, owner)
            return 201
        push.dispatch(self.root, sender)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 0)

    def test_sender_exception_410_deletes_subscription(self):
        self.record()
        self.register()
        self.record(activity())
        class Gone(Exception):
            response = type('Response', (), {'status_code': 410})()
        def sender(*_):
            raise Gone()
        self.assertEqual(push.dispatch(self.root, sender)['expired'], 1)
        self.assertEqual(push.dispatch(self.root, self.sender)['sent'], 0)

    def test_test_notification_requires_owner_and_explicit_call(self):
        owner = self.register()
        with patch.object(push, 'send', return_value=201) as sender:
            with self.assertRaises(ValueError):
                push.test_notification(self.root, dict(owner, token='wrong-token'))
            sender.assert_not_called()
            push.test_notification(self.root, owner)
            sender.assert_called_once()
            self.assertEqual(sender.call_args.args[2]['tag'], 'connection-test')

    def test_private_project_fields_never_enter_push_database(self):
        secret = 'PRIVATE-CV-PATH-AND-STUDENT-NAME'
        self.record()
        owner = self.register()
        self.record(activity(projects={'private': secret}, files=[secret], student_profile=secret))
        push.dispatch(self.root, self.sender)
        with push.database(self.root) as db:
            dump = '\n'.join(db.iterdump())
        self.assertNotIn(secret, dump)
        self.assertNotIn(owner['token'], dump)
        self.assertEqual(set(self.calls[0][1]), {'title', 'body', 'url', 'tag'})


if __name__ == '__main__':
    unittest.main()
