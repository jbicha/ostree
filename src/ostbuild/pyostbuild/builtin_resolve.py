# Copyright (C) 2011 Colin Walters <walters@verbum.org>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

import os,sys,subprocess,tempfile,re,shutil
import copy
import argparse
import json
import time
import urlparse
from StringIO import StringIO

from . import builtins
from .ostbuildlog import log, fatal
from .subprocess_helpers import run_sync, run_sync_get_output
from . import ostbuildrc
from . import vcs
from . import jsondb
from . import buildutil
from . import kvfile
from . import odict

class OstbuildResolve(builtins.Builtin):
    name = "resolve"
    short_description = "Expand git revisions in source to exact targets"

    def __init__(self):
        builtins.Builtin.__init__(self)

    def _resolve_component_meta(self, component_meta):
        result = dict(component_meta)
        orig_src = component_meta['src']

        did_expand = False
        for (vcsprefix, expansion) in self.snapshot['vcsconfig'].iteritems():
            prefix = vcsprefix + ':'
            if orig_src.startswith(prefix):
                result['src'] = expansion + orig_src[len(prefix):]
                did_expand = True
                break

        name = component_meta.get('name')
        if name is None:
            if did_expand:
                src = orig_src
                idx = src.rindex(':')
                name = src[idx+1:]
            else:
                src = result['src']
                idx = src.rindex('/')
                name = src[idx+1:]
            if name.endswith('.git'):
                name = name[:-4]
            name = name.replace('/', '-')
            result['name'] = name

        branch_or_tag = result.get('branch') or result.get('tag')
        if branch_or_tag is None:
            result['branch'] = 'master'

        return result
    
    def execute(self, argv):
        parser = argparse.ArgumentParser(description=self.short_description)
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--fetch-patches', action='store_true')
        parser.add_argument('components', nargs='*')

        args = parser.parse_args(argv)
        self.args = args
        
        self.parse_config()

        self.snapshot = json.load(open(args.manifest))
        self.prefix = self.snapshot['prefix']

        components = map(self._resolve_component_meta, self.snapshot['components'])
        self.snapshot['components'] = components

        global_patches_meta = self._resolve_component_meta(self.snapshot['patches'])
        self.snapshot['patches'] = global_patches_meta
        (keytype, uri) = vcs.parse_src_key(global_patches_meta['src'])
        mirrordir = vcs.ensure_vcs_mirror(self.mirrordir, keytype, uri, global_patches_meta['branch'])
        if args.fetch_patches:
            run_sync(['git', 'fetch'], cwd=mirrordir, log_initiation=False)
        revision = buildutil.get_git_version_describe(mirrordir, global_patches_meta['branch'])
        global_patches_meta['revision'] = revision

        unique_component_names = set()
        for component in components:
            (keytype, uri) = vcs.parse_src_key(component['src'])
            name = component['name']

            if name in unique_component_names:
                fatal("Duplicate component name '%s'" % (name, ))
            unique_component_names.add(name)

            branch_or_tag = component.get('branch') or component.get('tag')
            mirrordir = vcs.ensure_vcs_mirror(self.mirrordir, keytype, uri, branch_or_tag)
            revision = buildutil.get_git_version_describe(mirrordir, branch_or_tag)
            component['revision'] = revision

        src_db = self.get_src_snapshot_db()
        path = src_db.store(self.snapshot)
        log("Source snapshot: %s" % (path, ))
        
builtins.register(OstbuildResolve)
