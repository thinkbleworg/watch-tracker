import json
from unittest.mock import Mock
from config import get_source
from scrapers.hmt_official import OfficialHMTScraper
from tests.test_notifier import make_watch, FakeSession, FakeResponse
from notifier import TelegramNotifier
from database import Database


def test_json_filter_includes_unavailable():
    s=OfficialHMTScraper(get_source('hmt.in'))
    s._request=Mock(return_value=Mock(json=lambda:{'html':'<div>Coming Soon</div>'}))
    assert 'Coming Soon' in s._post_filter_products(2)
    assert s._request.call_args.kwargs['data']['availability_filter']=='-1'
    assert s._request.call_args.kwargs['data']['load_more_count']=='2'


def test_load_more_discovers_later_coming_soon():
    s=OfficialHMTScraper(get_source('hmt.in'))
    s._request=Mock(return_value=Mock(text=''))
    s._post_filter_products=Mock(side_effect=['<button id="loadMoreBtnData"></button>','done'])
    a=make_watch(); b=make_watch(); b.id='later'; b.availability='coming_soon'
    s._parse_product_cards=Mock(side_effect=[[a],[a,b]])
    assert len(s.scrape())==2
    assert [c.args[0] for c in s._post_filter_products.call_args_list] == [3, 4]


def test_image_cached_and_button_and_timezone(tmp_path):
    db=Database(tmp_path/'test.db');n=TelegramNotifier(db,bot_token='token',chat_id='chat')
    session=FakeSession(); n._session=session;n._pace=lambda:None
    w=make_watch();w.last_stock_check='2026-10-30T06:54:00+00:00'
    original=session.post
    def post(*a,**kw):
        original(*a,**kw)
        return FakeResponse({'ok':True,'result':{'photo':[{'file_id':'cached-photo'}]}})
    session.post=post
    n._send_watch_message(w,alert_type='new')
    n._send_watch_message(w,alert_type='back_in_stock')
    assert session.calls[1]['data']['photo']=='cached-photo'
    data=session.calls[0]['data']
    assert '30 Oct 2026, 12:24 pm' in data['caption']
    assert 'NEW WATCH LISTED' in data['caption']
    assert json.loads(data['reply_markup'])['inline_keyboard'][0][0]['url']==w.product_url


def test_three_page_response_without_more_stops_immediately():
    s=OfficialHMTScraper(get_source('hmt.in'))
    s._request=Mock(return_value=Mock(text=''))
    s._post_filter_products=Mock(return_value='<div>complete</div>')
    s._parse_product_cards=Mock(return_value=[make_watch()])
    assert len(s.scrape()) == 1
    s._post_filter_products.assert_called_once_with(3)
