#!/usr/bin/python3

from contextlib import closing
import io
import json
from string import Template
import sqlite3
import sys
import time
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
header_img = {'Content-type': 'image/png'}
header_ua = {'User-Agent': 'bitcointip.feuri.de/0.0.1'}


def extract_tips(raw_tips):
    # 1) get tipped comment
    #    http://bitcointip.net/tipped.php?subreddit=all&type=all&by=tipped&time=day&sort=last
    # 2) use link provided to find tipping comment :/
    # 3) get tip data
    #    http://bitcointip.net/api/gettips.php?tips=c7h194m,cd811o0
    # 4) get comment data
    #    http://www.reddit.com/api/info.json?id=t1_c7h194m
    tips = []
    for tip in raw_tips:
        data_tip = {}
        url_tipped = tip.xpath('td[@class="right"]/a')[0].get('href')
        data_tip['subreddit'] = tip.xpath('td[@class="right"]/span/a')[1].text
        data_tip['fullname'] = get_tipping_comment(url_tipped)
        if data_tip['fullname'] is None:
            continue
        c_data = get_comment_data(data_tip['fullname'].split('_')[1])
        if c_data is None:
            continue
        data_tip['amountBTC'] = c_data['amountBTC']
        data_tip['amountUSD'] = c_data['amountUSD']
        data_tip['sender'] = c_data['sender']
        data_tip['receiver'] = c_data['receiver']
        data_tip['time'] = get_comment_time(data_tip['fullname'])
        tips.append(data_tip)
    return(tips)


def get_tipping_comment(url):
    print(url)
    # dont know haw to view NSFW subreddit content yet, skip them for now
    if ('GirlsGoneBitcoin') in url:
        break
    toplevel = False
    url_split = url.split('/')
    if url_split[6] == url_split[8]:
        toplevel = True
    # TODO
    # - put next 5 lines into common function
    # - handle HTTPError 504 (Gateway Time-Out, just retry)
    req = Request(url, headers=header_ua)
    data = urlopen(req).read()
    buf = io.StringIO()
    buf.write(data.decode(errors='ignore'))
    buf.seek(0)
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
    return(comment_id)


def get_comment_data(comment_id):
    api_gettips = Template('http://bitcointip.net/api/gettips.php?tips=${cid}')
    req = Request(api_gettips.substitute(cid=comment_id), headers=header_ua)
    data = urlopen(req).read()
    buf = io.StringIO()
    buf.write(data.decode())
    buf.seek(0)
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
    req = Request(api_time.substitute(id=fullname), headers=header_ua)
    data = urlopen(req).read()
    buf = io.StringIO()
    buf.write(data.decode())
    buf.seek(0)
    data = json.load(buf)
    c_time = int(data['data']['children'][0]['data']['created_utc'])
    return(c_time)


def connect_db():
    return(sqlite3.connect('bitcointip.db'))


def update_db(tips):
    with closing(connect_db()) as db:
        c = db.cursor()
        # TODO to init method
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
    i = page
    while True:
        print('Page: {}'.format(i))
        raw_tips = download_data(url.substitute(time=time, site=i))
        if raw_tips is None:
            break

        tips = extract_tips(raw_tips)
        update_db(tips)
        i += 1


def plot_chart(tips, n_range,
               xlabel='Time ago',
               ylabel='Amount tipped (in USD)',
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
                      xlabel='Amount tipped (in USD)',
                      ylabel='Times tipped',
                      title='Tips so far'):
    tip_values = []
    for x in tips.values():
        for y in x:
            tip_values.append(y['amount'])
    bar_width = 0.5
    index = np.arange(8)
    separators = [500, 100, 25, 10, 5, 2.5, 1, 0]
    for i in index:
        amount = 0
        for tip in tip_values:
            if tip >= separators[i]:
                amount += 1
                tip_values.remove(tip)
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
    req = Request(url, headers=header_ua)
    data = urlopen(req).read()
    buf = io.StringIO()
    buf.write(data.decode(errors='ignore'))
    buf.seek(0)
    html = lxml.html.parse(buf).getroot()
    raw_tips = html.xpath('//div[@id="content"]/table//tr')
    if raw_tips == []:
        return(None)
    return(raw_tips)


def download_data_day():
    url = Template('http://bitcointip.net/tipped.php?subreddit=all&type=all&by=tipped&time=day&sort=last&page=${site}')
    tips = {}
    n_range = 25
    for i in range(n_range):
        tips[i] = []
    i = 1
    while True:
        raw_tips = download_data(url.substitute(site=i))
        if raw_tips is None:
            break

        tips = extract_tips(raw_tips, tips, 'hour')
        i += 1

    return(tips)


def download_data_week():
    url = Template('http://bitcointip.net/tipped.php?subreddit=all&type=all&by=tipped&time=week&sort=last&page=${site}')
    tips = {}
    n_range = 8
    for i in range(n_range):
        tips[i] = []
    i = 1
    while True:
        raw_tips = download_data(url.substitute(site=i))
        if raw_tips is None:
            break

        tips = extract_tips(raw_tips, tips, 'day')
        i += 1

    return(tips)


def download_data_month():
    url = Template('http://bitcointip.net/tipped.php?subreddit=all&type=all&by=tipped&time=month&sort=last&page=${site}')
    tips = {}
    n_range = 5
    for i in range(n_range):
        tips[i] = []
    i = 1
    while True:
        raw_tips = download_data(url.substitute(site=i))
        if raw_tips is None:
            break

        tips = extract_tips(raw_tips, tips, 'week')
        i += 1

    return(tips)


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
    return(render_template('base.html'))


@app.route('/charts/day.png')
def chart_day():
    data = cache.get('day_chart')
    if data is None:
        tips = {}
        n_range = 25
        db = getattr(g, 'db', None)
        with db:
            for i in range(n_range):
                tips[i] = []
                c = db.cursor()
                now = time.time()
                c.execute('SELECT amountBTC FROM tips WHERE time BETWEEN ? AND ?', (now - (i+1)*60*60,
                                                                                    now - i*60*60))
                for x in c:
                    tips[i].append(x[0])
        data = plot_chart(tips, 25,
                          xlabel='Time ago (in hours)',
                          title='Tips during the last 24 hours')
        cache.set('day_chart', data, 15*60)
    return(data, 200, header_img)


@app.route('/charts/day_tipped.png')
def chart_day_tipped():
    data = cache.get('day_chart_tipped')
    if data is None:
        tips = cache.get('day_tips')
        if tips is None:
            tips = download_data_day()
            cache.set('day_tips', tips, 15*60)
        data = plot_chart_tipped(tips,
                                 title='Tips during the last 24 hours')
        cache.set('day_chart_tipped', data, 15*60)
    return(data, 200, header_img)


@app.route('/charts/week.png')
def chart_week():
    data = cache.get('week_chart')
    if data is None:
        tips = {}
        n_range = 8
        db = getattr(g, 'db', None)
        with db:
            for i in range(n_range):
                tips[i] = []
                c = db.cursor()
                now = time.time()
                c.execute('SELECT amountBTC FROM tips WHERE time BETWEEN ? AND ?', (now - (i+1)*24*60*60,
                                                                                    now - i*24*60*60))
                for x in c:
                    tips[i].append(x[0])
        data = plot_chart(tips, 8,
                          xlabel='Time ago (in days)',
                          title='Tips during the last 7 days')
        cache.set('week_chart', data, 60*60)
    return(data, 200, header_img)


@app.route('/charts/week_tipped.png')
def chart_week_tipped():
    data = cache.get('week_chart_tipped')
    if data is None:
        tips = cache.get('week_tips')
        if tips is None:
            tips = download_data_week()
            cache.set('week_tips', tips, 60*60)
        data = plot_chart_tipped(tips,
                                 title='Tips during the last 7 days')
        cache.set('week_chart_tipped', data, 60*60)
    return(data, 200, header_img)


@app.route('/charts/month.png')
def chart_month():
    data = cache.get('month_chart')
    if data is None:
        tips = {}
        n_range = 5
        db = getattr(g, 'db', None)
        with db:
            for i in range(n_range):
                tips[i] = []
                c = db.cursor()
                now = time.time()
                c.execute('SELECT amountBTC FROM tips WHERE time BETWEEN ? AND ?', (now - (i+1)*7*24*60*60,
                                                                                    now - i*7*24*60*60))
                for x in c:
                    tips[i].append(x[0])
        data = plot_chart(tips, 5,
                          xlabel='Time ago (in weeks)',
                          title='Tips during the last 4 weeks')
        cache.set('month_chart', data, 24*60*60)
    return(data, 200, header_img)


@app.route('/charts/month_tipped.png')
def chart_month_tipped():
    data = cache.get('month_chart_tipped')
    if data is None:
        tips = cache.get('month_tips')
        if tips is None:
            tips = download_data_month()
            cache.set('month_tips', tips, 24*60*60)
        data = plot_chart_tipped(tips,
                                 title='Tips during the last 4 weeks')
        cache.set('month_chart_tipped', data, 24*60*60)
    return(data, 200, header_img)


@app.route('/imprint')
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
        sync(sys.argv[2], sys.argv[3])
    else:
        # serve, wrong amount of parameters
        sys.exit(app.run(debug=True))
