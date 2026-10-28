"""Lose one real accepted response through the local fixture, then safely replay."""
import argparse
import http.client
import json
import time
import urllib.request
from pathlib import Path
from neo4j import GraphDatabase


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runtime', required=True, type=Path)
    ap.add_argument('--proxy', required=True)
    args = ap.parse_args()
    root = args.runtime
    control = root / 'fixture/control.json'
    state = json.loads(control.read_text())
    state['drop_next'] = True
    control.write_text(json.dumps(state))
    payload = {'group_id': 'lost-receipt-' + str(time.time_ns()), 'name': 'assistant-v3-lost-receipt',
               'body': '阿澄把蓝色地图收藏在图书馆，林舟负责登记归还时间。', 'message_id': 'lost-receipt-source'}

    def post():
        req = urllib.request.Request(args.proxy + '/assistant/submit', data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
        return json.load(urllib.request.urlopen(req, timeout=30))

    try:
        post()
        raise AssertionError('fixture did not drop the accepted response')
    except (http.client.RemoteDisconnected, ConnectionResetError):
        pass
    assert json.loads(control.read_text())['drop_next'] is False
    for _ in range(200):
        if post()['status'] == 'completed':
            break
        time.sleep(3)
    else:
        raise TimeoutError('lost response replay failed to complete')
    pw = dict(x.split('=', 1) for x in (root / 'neo4j.env').read_text().splitlines())['NEO4J_AUTH'].split('/', 1)[1]
    with GraphDatabase.driver('bolt://127.0.0.1:17689', auth=('neo4j', pw)) as driver:
        turn = driver.execute_query('MATCH (t:AssistantTurn {group_id:$gid,name:$name}) RETURN count(t) AS n',
                                    gid=payload['group_id'], name=payload['name']).records[0]['n']
        episodes = driver.execute_query('MATCH (e:Episodic {group_id:$gid,name:$name}) RETURN count(e) AS n',
                                        gid=payload['group_id'], name=payload['name']).records[0]['n']
    assert turn == episodes == 1
    result = {'check': 'PASS lost accepted response replayed without duplicate summary job or episode',
              'assistant_jobs': turn, 'episodes': episodes}
    (root / 'lost-receipt-result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
