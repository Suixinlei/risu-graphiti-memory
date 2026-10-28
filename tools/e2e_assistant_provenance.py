"""Seed one synthetic legacy edge in an explicit test Neo4j; check HTTP filtering."""
import argparse
import json
import uuid
import urllib.request
from pathlib import Path
from neo4j import GraphDatabase


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runtime', required=True, type=Path)
    ap.add_argument('--base', required=True)
    args = ap.parse_args()
    root = args.runtime
    # This fixture is only for the isolated runtime created for this acceptance.
    group = json.loads((root / 'test-config.json').read_text())['group']
    password = dict(line.split('=', 1) for line in (root / 'neo4j.env').read_text().splitlines())['NEO4J_AUTH'].split('/', 1)[1]
    marker = 'LEGACY_ONLY_SENTINEL'
    with GraphDatabase.driver('bolt://127.0.0.1:17689', auth=('neo4j', password)) as driver:
        rows = driver.execute_query(
            'MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) WHERE r.group_id=$gid '
            'WITH a,r,b LIMIT 1 '
            'CREATE (e:Episodic {uuid:$ep,name:$name,group_id:$gid,content:$fact}) '
            'CREATE (a)-[legacy:RELATES_TO]->(b) SET legacy=properties(r) '
            'SET legacy.uuid=$edge,legacy.fact=$fact,legacy.name=$name,legacy.episodes=[$ep] '
            'RETURN legacy.uuid AS uuid',
            gid=group, ep=str(uuid.uuid4()), edge=str(uuid.uuid4()), name=marker,
            fact=marker + '：蓝色地图还有一个未经 assistant 确认的旧来源事实。')
        assert rows.records

    def request(path):
        req = urllib.request.Request(args.base + path, data=json.dumps({
            'group_id': group, 'query': marker + ' 蓝色地图', 'limit': 50}).encode(),
            headers={'Content-Type': 'application/json'})
        return json.load(urllib.request.urlopen(req, timeout=30))

    legacy = request('/search')
    filtered = request('/memory')
    assert any(marker in f['fact'] for f in legacy['facts']), 'legacy fixture was not searchable'
    assert filtered['facts'] and not any(marker in f['fact'] for f in filtered['facts'])
    result = {'check': 'PASS legacy-only facts excluded from assistant memory',
              'legacy_marker_searchable': True, 'new_memory_marker_excluded': True,
              'new_assistant_facts_returned': len(filtered['facts'])}
    (root / 'provenance-result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
