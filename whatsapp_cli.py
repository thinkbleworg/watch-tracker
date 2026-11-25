"""Operator-only commands. No new public HTTP endpoint can send WhatsApp posts."""
import argparse
import json
import sys

from config import config
from database import Database
from whatsapp_notifier import WhatsAppNotifier, DeliveryError


def main():
    parser = argparse.ArgumentParser(description='HMT WhatsApp Channel tools')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='Show delivery counts')
    commands.add_parser('test-text', help='Publish one clearly labelled test post')
    image = commands.add_parser('test-image', help='Publish one image test post')
    group = image.add_mutually_exclusive_group(required=True)
    group.add_argument('--url', help='Public image URL')
    group.add_argument('--watch-id', help='Use an existing catalogue watch image')
    retry = commands.add_parser('retry', help='Requeue after checking the actual Channel')
    retry.add_argument('alert_id', type=int)
    retry.add_argument('--confirm-not-posted', action='store_true', required=True)
    args = parser.parse_args()
    db = Database(config.database_path)
    notifier = WhatsAppNotifier(db, config.whatsapp)
    try:
        if args.command == 'status':
            print(json.dumps({'enabled': config.whatsapp.enabled, 'configured': config.whatsapp.configured,
                              'status_counts': notifier.status_counts()}, indent=2))
        elif args.command == 'retry':
            if not notifier.retry(args.alert_id):
                raise ValueError('Alert not found, wrong target, or not failed/uncertain')
            print('Requeued; running worker will process it if enabled and still within max age.')
        else:
            caption = '⌚ *HMT Watch Tracker — TEST*\nThis is a test notification, not a stock alert.'
            url = None
            if args.command == 'test-image':
                url = args.url
                if args.watch_id:
                    watch = db.get_watch(args.watch_id)
                    if not watch or not watch.image_url:
                        raise ValueError('Watch not found or has no image URL')
                    url = watch.image_url
            print('WAHA accepted message:', notifier.send(caption, url))
            print('Open WhatsApp and verify the post actually appeared in your Channel.')
    except (DeliveryError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
