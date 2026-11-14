"""Control child: deliberately orphan only labeled synthetic resources."""
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from ownership import install

ledger = Path(os.environ['HLA_UI_QUAL_LEDGER'])
token = os.environ['HLA_UI_QUAL_TOKEN']
install(ledger, token)
name = 'hla-ui-owner-control-' + uuid.uuid4().hex[:12]
image = 'sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53'
subprocess.run(['docker', 'run', '-d', '--name', name, '--network', 'none', image,
                'node', '-e', 'setInterval(()=>{},1000)'], check=True, capture_output=True, text=True)
next_path = ledger.parent / 'next'
next_path.write_text('#!/bin/sh\nexec sleep 120\n')
next_path.chmod(0o700)
subprocess.Popen([str(next_path), 'start'], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print('child created owned container and process', flush=True)
print('synthetic partial diagnostic', file=sys.stderr, flush=True)
time.sleep(120)
