import copy, unittest
from binding import guard

def fixture():
 c={'sha':'a'*40,'project':'lane-dev-train-x','train_id':'train-x','source_path':'/checked','network_id':'n'}
 b={'sha':c['sha'],'clean':True,'all_context_digest':'ctx','dockerfile_digest':'df','dockerignore_digest':'di'}
 build={'train_id':'train-x','checked_sha':c['sha'],'passed':True,'source_path':'/checked','output_capture':'direct-child-stdout-attested','web_build_image':'sha256:'+'b'*64,'api_build_image':'sha256:'+'c'*64}
 def service(kind): return {'image':build[kind+'_build_image'],'running':True,'project':c['project'],'service':kind,'url':'http://127.0.0.1:1234','url_proved_by_docker_inspect':True,'network_id':'n','api_dns_only_expected':True,'api_base_url':'http://api:8080'}
 return c,b,copy.deepcopy(b),build,service('web'),service('api')
class BindingTests(unittest.TestCase):
 def setUp(self): self.args=fixture()
 def test_good_synthetic(self): self.assertTrue(guard(*self.args))
 def bad(self,index,key,value):
  args=copy.deepcopy(self.args);args[index][key]=value
  with self.assertRaises(ValueError): guard(*args)
 def test_wrong_web_image(self): self.bad(4,'image','sha256:'+'f'*64)
 def test_wrong_web_url(self): self.bad(4,'url','http://example.com:1234')
 def test_wrong_context(self): self.bad(2,'all_context_digest','other')
 def test_wrong_source(self): self.bad(3,'source_path','/other')
 def test_unobserved_build(self): self.bad(3,'output_capture','caller-says-so')
 def test_wrong_backend(self): self.bad(4,'api_base_url','http://elsewhere:8080')
 def test_wrong_network(self): self.bad(4,'network_id','wrong')
 def test_unproven_port(self): self.bad(4,'url_proved_by_docker_inspect',False)
if __name__=='__main__':unittest.main()
