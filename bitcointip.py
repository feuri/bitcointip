#!/usr/bin/python3

import concurrent.futures
from contextlib import closing
import io
from itertools import count
import json
from string import Template
import sqlite3
import sys
import time
from urllib.error import HTTPError
from urllib.request import urlopen, Request

from flask import Flask, g, render_template
import lxml.html
import matplotlib
matplotlib.use('Agg')
import numpy as np
import matplotlib.pyplot as plt
from werkzeug.contrib.cache import FileSystemCache

app = Flask(__name__)
cache = FileSystemCache('cache/')
cache_timeout = 15*60  # 15 minutes
header_img = {'Content-type': 'image/png'}
header_ua = {'User-Agent': 'bitcointip.feuri.de/0.0.1'}
query_all = 'SELECT amountBTC FROM tips WHERE time BETWEEN ? AND ?'
query_subreddit = 'SELECT amountBTC FROM tips WHERE subreddit = ? AND time BETWEEN ? AND ?'


def load_url(url):
    # TODO handle HTTPError 504 (Gateway Time-Out, just retry)
    req = Request(url, headers=header_ua)
    try:
        data = urlopen(req).read()
    except HTTPError:
        return(None)
    buf = io.StringIO()
    buf.write(data.decode(errors='ignore'))
    buf.seek(0)
    return(buf)


def extract_tips(raw_tips):
    # 1) get tipped comment
    #    http://bitcointip.net/tipped.php?subreddit=all&type=all&by=tipped&time=day&sort=last
    # 2) use link provided to find tipping comment :/
    # 3) get tip data
    #    http://bitcointip.net/api/gettips.php?tips=c7h194m,cd811o0
    # 4) get comment data
    #    http://www.reddit.com/api/info.json?id=t1_c7h194m
    tips = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_tip = {executor.submit(extract_tip, tip): tip for tip in raw_tips}
        for future in concurrent.futures.as_completed(future_to_tip):
            if(future.result() is not None):
                tips.append(future.result())
    return(tips)


def extract_tip(tip):
    try:
        data_tip = {}
        url_tipped = tip.xpath('td[@class="right"]/a')[0].get('href')
        data_tip['subreddit'] = tip.xpath('td[@class="right"]/span/a')[1].text
        # skip comment for now if no tip is found
        # TODO: proper error handling
        try:
            data_tip['fullname'] = get_tipping_comment(url_tipped)
        except:
            return(None)
        if data_tip['fullname'] is None:
            return(None)
        c_data = get_comment_data(data_tip['fullname'].split('_')[1])
        if c_data is None:
            return(None)
        data_tip['amountBTC'] = c_data['amountBTC']
        data_tip['amountUSD'] = c_data['amountUSD']
        data_tip['sender'] = c_data['sender']
        data_tip['receiver'] = c_data['receiver']
        data_tip['time'] = get_comment_time(data_tip['fullname'])
    except KeyboardInterrupt:
        raise
    return(data_tip)


def get_tipping_comment(url):
    try:
        print(url)
        # dont know how to view private/NSFW subreddit content yet, skip them for now
        url_split = url.split('/')
        if url_split[4] in ('GirlsGoneBitcoin', 'cpn'):
            return(None)
        toplevel = False
        if url_split[6] == url_split[8]:
            toplevel = True
        buf = load_url(url)
        html = lxml.html.parse(buf).getroot()
        # bitcointip_keywords = ('+/u/bitcointip')
        comment_id = None
        if toplevel:
            comment_list = html.xpath('//div[@class="commentarea"]/div[@class="sitetable nestedlisting"]/div[@data-fullname]')
            if len(comment_list) == 0:
                comment_id = comment_list[0].get('data-fullname')
            else:
                for c in comment_list:
                    if '+/u/bitcointip' in c.xpath('div[contains(@class, "entry")]/div[@class="noncollapsed"]/form[@class="usertext"]/div[@class="usertext-body"]/div[@class="md"]')[0].text_content():
                        comment_id = c.get('data-fullname')
                        break
        else:
            comment_list = html.xpath('//div[@class="commentarea"]/div[@class="sitetable nestedlisting"]/div/div[@class="child"]/div/div[@data-fullname]')
            if len(comment_list) == 1:
                comment_id = comment_list[0].get('data-fullname')
            else:
                for c in comment_list:
                    if '+/u/bitcointip' in c.xpath('div[contains(@class, "entry")]/div[@class="noncollapsed"]/form[@class="usertext"]/div[@class="usertext-body"]/div[@class="md"]')[0].text_content():
                        comment_id = c.get('data-fullname')
                        break
    except KeyboardInterrupt:
        raise
    return(comment_id)


def get_comment_data(comment_id):
    api_gettips = Template('http://bitcointip.net/api/gettips.php?tips=${cid}')
    buf = load_url(api_gettips.substitute(cid=comment_id))
    data = json.load(buf)
    if data['tips'] == []:
        return(None)
    c_data = {}
    c_data['amountBTC'] = data['tips'][0]['amountBTC']
    c_data['amountUSD'] = data['tips'][0]['amountUSD']
    c_data['sender'] = data['tips'][0]['sender']
    c_data['receiver'] = data['tips'][0]['receiver']
    return(c_data)


def get_comment_time(fullname):
    api_time = Template('http://www.reddit.com/api/info.json?id=${id}')
    buf = load_url(api_time.substitute(id=fullname))
    data = json.load(buf)
    c_time = int(data['data']['children'][0]['data']['created_utc'])
    return(c_time)


def connect_db(rw=False):
    # ro is supported in python 3.4+
    # http://docs.python.org/3.4/library/sqlite3.html#sqlite3.connect
    #if rw:
    #    return(sqlite3.connect('bitcointip.db'))
    #else:
    #    return(sqlite3.connect('file:bitcointip.db?mode=ro', uri=True))
    return(sqlite3.connect('bitcointip.db'))


def update_db(tips):
    with closing(connect_db()) as db:
        c = db.cursor()
        # TODO: to init method
        c.execute('CREATE TABLE IF NOT EXISTS tips (id TEXT UNIQUE, amountBTC REAL, amountUSD REAL, time INTEGER, sender TEXT, receiver TEXT, subreddit TEXT)')
        with db:
            c = db.cursor()
            for tip in tips:
                try:
                    c.execute('INSERT INTO tips VALUES (?, ?, ?, ?, ?, ?, ?)', (tip['fullname'],
                                                                                tip['amountBTC'],
                                                                                tip['amountUSD'],
                                                                                tip['time'],
                                                                                tip['sender'],
                                                                                tip['receiver'],
                                                                                tip['subreddit']))
                except sqlite3.IntegrityError as e:
                    # c.execute() yields a 'sqlite3.IntegrityError' if id (type: TEXT UNIQUE) is not unique
                    print('tip {} already in db, skipping (SQL: {})'.format(tip['fullname'], e))


def sync(time='hour', page=1):
    url = Template('http://bitcointip.net/tipped.php?subreddit=all&type=all&by=tipped&time=${time}&sort=last&page=${site}')
    tips = {}
    for i in count(page):
        print('Page: {}'.format(i))
        try:
            raw_tips = download_data(url.substitute(time=time, site=i))
            if raw_tips is None:
                break
        except KeyboardInterrupt:
            break
        tips = extract_tips(raw_tips)
        update_db(tips)


def plot_chart(tips, n_range,
               xlabel='Time ago',
               ylabel='Amount tipped (in BTC)',
               title='Tips so far'):
    bar_width = 0.5
    index = np.arange(n_range)
    for i in index:
        amount = 0
        for tip in tips[i]:
            amount += tip
        plt.bar(i, amount, bar_width, alpha=0.4)

    plt.xticks(index + bar_width/2, index)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    ax = plt.subplot(111)
    ax.yaxis.grid(color='gray', linestyle=':')
    ax.annotate('Updated: {}'.format(time.strftime('%Y-%m-%d %H:%M %z')),
                fontsize=9, color='gray',
                xy=(1, 0), xycoords='axes fraction',
                xytext=(0, -25), textcoords='offset points',
                ha='right', va='top')
    f = io.BytesIO()
    plt.savefig(f, format='png')
    f.seek(0)
    data = f.read()
    plt.cla()
    return(data)


def plot_chart_tipped(tips,
                      xlabel='Amount tipped (in BTC)',
                      ylabel='Times tipped',
                      title='Tips so far'):
    bar_width = 0.5
    # USD
    #separators = [500, 100, 25, 10, 5, 2.5, 1, 0]
    # BTC
    separators = [1, 0.5, 0.01, 0.005, 0.001, 0]
    index = np.arange(len(separators))
    for i in index:
        amount = 0
        for tip in tips:
            if tip >= separators[i]:
                amount += 1
                tips.remove(tip)
        plt.bar(i, amount, bar_width, alpha=0.4)

    plt.xticks(index + bar_width/2, index)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    ax = plt.subplot(111)
    ax.set_xticklabels(['>'+str(x) for x in separators])
    ax.yaxis.grid(color='gray', linestyle=':')
    ax.annotate('Updated: {}'.format(time.strftime('%Y-%m-%d %H:%M %z')),
                fontsize=9, color='gray',
                xy=(1, 0), xycoords='axes fraction',
                xytext=(0, -25), textcoords='offset points',
                ha='right', va='top')
    f = io.BytesIO()
    plt.savefig(f, format='png')
    f.seek(0)
    data = f.read()
    plt.cla()
    return(data)


def download_data(url):
    buf = load_url(url)
    html = lxml.html.parse(buf).getroot()
    raw_tips = html.xpath('//div[@id="content"]/table//tr')
    if raw_tips == []:
        return(None)
    return(raw_tips)


@app.before_request
def before_request():
    g.db = connect_db()


@app.teardown_request
def teardown_request(exception):
    db = getattr(g, 'db', None)
    if db is not None:
        db.close()


@app.route('/')
def index():
    db = getattr(g, 'db', None)
    with db:
        c = db.cursor()
        c.execute('SELECT sum(amountBTC) FROM tips')
        total_btc = '{:.4f}'.format(c.fetchone()[0])
        c.execute('SELECT count(id) FROM tips')
        num_tips = '{}'.format(c.fetchone()[0])
        c.execute('SELECT avg(amountBTC) FROM tips')
        average_btc = '{:.4f}'.format(c.fetchone()[0])
    return(render_template('base.html', total=total_btc, amount=num_tips, average=average_btc, subreddit='all'))


@app.route('/r/<subreddit>/')
def subreddit_stats(subreddit):
    if(subreddit == 'all'):
        return(index())
    db = getattr(g, 'db', None)
    with db:
        c = db.cursor()
        c.execute('SELECT sum(amountBTC) FROM tips WHERE subreddit = ?', [subreddit])
        total_btc = '{:.4f}'.format(c.fetchone()[0])
        c.execute('SELECT count(id) FROM tips WHERE subreddit = ?', [subreddit])
        num_tips = '{}'.format(c.fetchone()[0])
        c.execute('SELECT avg(amountBTC) FROM tips WHERE subreddit = ?', [subreddit])
        average_btc = '{:.4f}'.format(c.fetchone()[0])
    return(render_template('base.html', total=total_btc, amount=num_tips, average=average_btc, subreddit=subreddit))


@app.route('/r/<subreddit>/charts/day.png')
def chart_day(subreddit):
    cache_id = '_'.join(['chart_day', subreddit])
    data = cache.get(cache_id)
    if data is None:
        tips = {}
        n_range = 25
        db = getattr(g, 'db', None)
        with db:
            now = time.time()
            for i in range(n_range):
                tips[i] = []
                c = db.cursor()
                if(subreddit == 'all'):
                    c.execute(query_all, (now - (i+1)*60*60, now - i*60*60))
                else:
                    c.execute(query_subreddit, (subreddit, now - (i+1)*60*60, now - i*60*60))
                for x in c:
                    tips[i].append(x[0])
        data = plot_chart(tips, 25,
                          xlabel='Time ago (in hours)',
                          title='Tips during the last 24 hours')
        cache.set(cache_id, data, cache_timeout)
    return(data, 200, header_img)


@app.route('/r/<subreddit>/charts/day_tipped.png')
def chart_day_tipped(subreddit):
    cache_id = '_'.join(['chart_day_tipped', subreddit])
    data = cache.get(cache_id)
    if data is None:
        tips = []
        db = getattr(g, 'db', None)
        with db:
            c = db.cursor()
            now = time.time()
            if(subreddit == 'all'):
                c.execute(query_all, (now - 24*60*60, now))
            else:
                c.execute(query_subreddit, (subreddit, now - 24*60*60, now))
            for x in c:
                tips.append(x[0])
        data = plot_chart_tipped(tips,
                                 title='Tips during the last 24 hours')
        cache.set(cache_id, data, cache_timeout)
    return(data, 200, header_img)


@app.route('/r/<subreddit>/charts/week.png')
def chart_week(subreddit):
    cache_id = '_'.join(['chart_week', subreddit])
    data = cache.get(cache_id)
    if data is None:
        tips = {}
        n_range = 8
        db = getattr(g, 'db', None)
        with db:
            now = time.time()
            for i in range(n_range):
                tips[i] = []
                c = db.cursor()
                if(subreddit == 'all'):
                    c.execute(query_all, (now - (i+1)*24*60*60, now - i*24*60*60))
                else:
                    c.execute(query_subreddit, (subreddit, now - (i+1)*24*60*60, now - i*24*60*60))
                for x in c:
                    tips[i].append(x[0])
        data = plot_chart(tips, 8,
                          xlabel='Time ago (in days)',
                          title='Tips during the last 7 days')
        cache.set(cache_id, data, cache_timeout)
    return(data, 200, header_img)


@app.route('/r/<subreddit>/charts/week_tipped.png')
def chart_week_tipped(subreddit):
    cache_id = '_'.join(['chart_week_tipped', subreddit])
    data = cache.get(cache_id)
    if data is None:
        tips = []
        db = getattr(g, 'db', None)
        with db:
            c = db.cursor()
            now = time.time()
            if(subreddit == 'all'):
                c.execute(query_all, (now - 7*24*60*60, now))
            else:
                c.execute(query_subreddit, (subreddit, now - 7*24*60*60, now))
            for x in c:
                tips.append(x[0])
        data = plot_chart_tipped(tips,
                                 title='Tips during the last 7 days')
        cache.set(cache_id, data, cache_timeout)
    return(data, 200, header_img)


@app.route('/r/<subreddit>/charts/month.png')
def chart_month(subreddit):
    cache_id = '_'.join(['chart_month', subreddit])
    data = cache.get(cache_id)
    if data is None:
        tips = {}
        n_range = 5
        db = getattr(g, 'db', None)
        with db:
            now = time.time()
            for i in range(n_range):
                tips[i] = []
                c = db.cursor()
                if(subreddit == 'all'):
                    c.execute(query_all, (now - (i+1)*7*24*60*60, now - i*7*24*60*60))
                else:
                    c.execute(query_subreddit, (subreddit, now - (i+1)*7*24*60*60, now - i*7*24*60*60))
                for x in c:
                    tips[i].append(x[0])
        data = plot_chart(tips, 5,
                          xlabel='Time ago (in weeks)',
                          title='Tips during the last 4 weeks')
        cache.set(cache_id, data, cache_timeout)
    return(data, 200, header_img)


@app.route('/r/<subreddit>/charts/month_tipped.png')
def chart_month_tipped(subreddit):
    cache_id = '_'.join(['chart_month_tipped', subreddit])
    data = cache.get(cache_id)
    if data is None:
        tips = []
        db = getattr(g, 'db', None)
        with db:
            c = db.cursor()
            now = time.time()
            if(subreddit == 'all'):
                c.execute(query_all, (now - 4*24*60*60, now))
            else:
                c.execute(query_subreddit, (subreddit, now - 4*24*60*60, now))
            for x in c:
                tips.append(x[0])
        data = plot_chart_tipped(tips,
                                 title='Tips during the last 4 weeks')
        cache.set(cache_id, data, cache_timeout)
    return(data, 200, header_img)


@app.route('/imprint/')
def imprint():
    return(render_template('imprint.html'))

if __name__ == '__main__':
    if len(sys.argv) == 1:
        # serve
        sys.exit(app.run(debug=True))
    elif len(sys.argv) == 2:
        if sys.argv[1] == 'help':
            pass
        elif sys.argv[1] == 'sync':
            sync()
    elif len(sys.argv) == 3:
        sync(sys.argv[2])
    elif len(sys.argv) == 4:
        sync(sys.argv[2], int(sys.argv[3]))
    else:
        sys.exit()
