"""Fail-closed, pure binding checks; inputs must come from trusted independent probes."""
import re
from urllib.parse import urlparse

def guard(c, before, after, build, web, api):
 def req(ok,msg):
  if not ok: raise ValueError(msg)
 req(re.fullmatch(r'[0-9a-f]{40}',c.get('sha','')),'invalid SHA')
 req(c.get('project')=='lane-dev-'+c.get('train_id','!'),'project mismatch')
 req(before==after and before.get('sha')==c['sha'] and before.get('clean') is True,'source/context changed or unclean')
 req(before.get('all_context_digest') and before.get('dockerfile_digest') and before.get('dockerignore_digest'),'missing context proof')
 req(build.get('train_id')==c['train_id'] and build.get('checked_sha')==c['sha'] and build.get('passed') is True,'train receipt mismatch')
 req(build.get('output_capture')=='direct-child-stdout-attested' and build.get('source_path')==c.get('source_path'),'unverified successful build output')
 for service,actual in [('web',web),('api',api)]:
  image=build.get(service+'_build_image','')
  req(re.fullmatch(r'sha256:[0-9a-f]{64}',image),'missing build image')
  req(actual.get('image')==image and actual.get('running') is True,'wrong '+service+' image')
  req(actual.get('project')==c['project'] and actual.get('service')==service,'wrong '+service+' container context')
  parsed=urlparse(actual.get('url',''))
  req(parsed.scheme=='http' and parsed.hostname=='127.0.0.1' and parsed.port and parsed.path in ('','/') and not parsed.query and not parsed.fragment and not parsed.username,'wrong '+service+' URL')
  req(actual.get('url_proved_by_docker_inspect') is True,'URL port not bound to container')
 req(web.get('network_id')==api.get('network_id')==c.get('network_id') and c.get('network_id'),'network mismatch')
 req(web.get('api_dns_only_expected') is True and web.get('api_base_url')=='http://api:8080','wrong web API audience')
 return True
