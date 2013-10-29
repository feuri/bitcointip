#!/usr/bin/python3

import io
from string import Template
import sys
import time
from urllib.request import urlopen, Request

from flask import Flask, render_template
import lxml.html
import matplotlib
matplotlib.use('Agg')
import numpy as np
import matplotlib.pyplot as plt
from werkzeug.contrib.cache import FileSystemCache

app = Flask(__name__)
cache = FileSystemCache('cache/')


def extract_tips(raw_tips, tips, timespan):
    for tip in raw_tips:
        data = {'amount': 0.00,
                'subreddit': '',
                'user': ''}
        time_ago = tip.xpath('td[@class="right"]/span')[0].text_content()
        time_ago = time_ago.split('\n')[1]
        time_ago = time_ago.split(' ')
        time_ago = 0 if not timespan in time_ago[3] else int(time_ago[2])
        data['amount'] = float(tip.xpath('td[@class="left"]/a')[0].text_content()[1:])
        data['subreddit'] = tip.xpath('td[@class="right"]/span/a')[1].text
        data['user'] = tip.xpath('td[@class="right"]/span/a')[0].text
        tips[time_ago].append(data)
    return(tips)


def plot_chart(tips, n_range,
               xlabel='Time ago',
               ylabel='Amount tipped (in USD)',
               title='Tips so far'):
    bar_width = 0.5
    index = np.arange(n_range)
    for i in index:
        amount = 0
        for tip in tips[i]:
            amount += tip['amount']
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
                      xlabel='Times tipped',
                      ylabel='Amount tipped (in USD)',
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
    req = Request(url)
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


@app.route('/')
def index():
    return(render_template('base.html'))


@app.route('/charts/day.png')
def chart_day():
    header = {'Content-type': 'image/png'}
    data = cache.get('day_chart')
    if data is None:
        tips = cache.get('day_tips')
        if tips = None:
            tips = download_data_day()
            cache.set('day_tips', tips, 15*60)
        data = plot_chart(tips, 25,
                          xlabel='Time ago (in hours)',
                          title='Tips during the last 24 hours')
        cache.set('day_chart', data, 15*60)
    return(data, 200, header)


@app.route('/charts/day_tipped.png')
def chart_day_tipped():
    header = {'Content-type': 'image/png'}
    data = cache.get('day_chart_tipped')
    if data is None:
        tips = cache.get('day_tips')
        if tips = None:
            tips = download_data_day()
            cache.set('day_tips', tips, 15*60)
        data = plot_chart_tipped(tips,
                                 xlabel='Time ago (in hours)',
                                 title='Tips during the last 24 hours')
        cache.set('day_chart_tipped', data, 15*60)
    return(data, 200, header)


@app.route('/charts/week.png')
def chart_week():
    header = {'Content-type': 'image/png'}
    data = cache.get('week_chart')
    if data is None:
        tips = cache.get('week_tips')
        if tips = None:
            tips = download_data_week()
            cache.set('week_tips', tips, 60*60)
        data = plot_chart(tips, 8,
                          xlabel='Time ago (in days)',
                          title='Tips during the last 7 days')
        cache.set('week_chart', data, 60*60)
    return(data, 200, header)


@app.route('/charts/week_tipped.png')
def chart_week_tipped():
    header = {'Content-type': 'image/png'}
    data = cache.get('week_chart_tipped')
    if data is None:
        tips = cache.get('week_tips')
        if tips = None:
            tips = download_data_week()
            cache.set('week_tips', tips, 60*60)
        data = plot_chart_tipped(tips,
                                 xlabel='Time ago (in days)',
                                 title='Tips during the last 7 days')
        cache.set('week_chart_tipped', data, 60*60)
    return(data, 200, header)


@app.route('/charts/month.png')
def chart_month():
    header = {'Content-type': 'image/png'}
    data = cache.get('month_chart')
    if data is None:
        tips = cache.get('month_tips')
        if tips = None:
            tips = download_data_month()
            cache.set('month_tips', tips, 24*60*60)
        data = plot_chart(tips, 5,
                          xlabel='Time ago (in weeks)',
                          title='Tips during the last 4 weeks')
        cache.set('month_chart', data, 24*60*60)
    return(data, 200, header)


@app.route('/charts/month_tipped.png')
def chart_month_tipped():
    header = {'Content-type': 'image/png'}
    data = cache.get('month_chart_tipped')
    if data is None:
        tips = cache.get('month_tips')
        if tips = None:
            tips = download_data_month()
            cache.set('month_tips', tips, 24*60*60)
        data = plot_chart_tipped(tips,
                                 xlabel='Time ago (in weeks)',
                                 title='Tips during the last 4 weeks')
        cache.set('month_chart_tipped', data, 24*60*60)
    return(data, 200, header)


@app.route('/imprint')
def imprint():
    return(render_template('imprint.html'))

if __name__ == '__main__':
    sys.exit(app.run(debug=True))
