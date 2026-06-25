# service-selinux

SELinux policy for kolla containers via security_opt.

A role to:

1. Add the `--security_opt` flag to all containers that
   do not start with the `--privilege` flag.
2. Optionally apply domain labels to each kolla service container.
3. n thOptionally apply policy rules to each SELinux domain, allowing
   any policy violations to be easily mapped back to the offending
   container.

## Background

## Unconfined containers

The assumption has been that Docker and the OpenStack containers
run in an unconfined state. In SELinux,this is observed as
"super powered container" mode. A linux admin can determine a container's
running policy state with `ps -eZ` which will display the
user, role, type, and sensitivity of a process. For example:

```
$ ps -eZ | grep node_exporter
    system_u:system_r:spc_t:s0       217056 ?        00:25:54 node_exporter
```
A few things trigger a container to have elevated spc privs upon start.
Two common approaches we've had to date in kolla-ansible include the following:

- Add `--privileged` to a container's start command.
- Start a docker container with `--pid host`

For a clear overview, reference Daniel Walsh's (My advice on SELinux container labeling)[https://developers.redhat.com/articles/2025/04/11/my-advice-selinux-container-labeling].

Check if a container started as `--privileged`:

```
docker inspect prometheus_node_exporter --format '{{ .HostConfig.Privileged }}'
```

If that returns true, Docker ignores any security_opt labels you might apply and falls back to spc_t. You cannot confine a privileged container with a custom SELinux domain. It doesn't work that way.

### IPC mode and PID mode

Docker is pretty dumb when it comes to SELinux. It's either all-in privileged or it's running a container confined. The "toe in the water" approach where an admin might thing apply IPC or PID mode to a container just gets full superpower ipc_t mode. Pretending ocker does otherwise is a bit of a fantasy. Check your modes with this:

```
docker ps --format '{{.Names}}' | xargs -I {} sh -c 'echo "{}: PidMode=$(docker inspect {} --format "{{ .HostConfig.PidMode }}") IpcMode=$(docker inspect {} --format "{{ .HostConfig.IpcMode}}")"'

docker inspect --format '{{.Name}} | {{.HostConfig.SecurityOpt}}' $(docker ps -q) | column -t -s "|"
```


## Proposed solution

Create SELinux policy for each OpenStack container giving each container the access it requires, nothing more.

## Considerations

**File system labels:** These are going to be some work on an installation. A container may need shared access with system processes, for example `/var/log/*` or with mounted shared file systems.


## Requirements

For consistenctcy, the security_opt labels match the pattern `kolla_<container_name>_t`.

For example, in the file `kolla-ansible/ansible/roles/prometheus-node-exporters/defaults/main.yml` under prometheus_service.prometheus-node-exporter, there's a value for the container_name:

`container_name: "prometheus_node_exporter"`

The security_opt label attached to the Docker command that launches that container would then be: `kolla_prometheus_node_exporter_t` and the corresponding selinux **domain** variable would be `kolla_prometheus_node_exporter_t`.

**IMPORTANT** The domain variable for a container's policy ***must match the security_opt label exactly***, otherwise SELinux audit logs (in audit.log) will not correctly tag AVC denials for the container, and you will find it very difficult to troubleshoot SELinux issues.


## Testing

Testing modules required:

```text
pytest
oslotest
docker
podman
```

### Tested OSs

- Rocky Linux 10.2
- ansible_os_family == 'RedHat' and ansible_distribution_major_version | int >= 9


## How does all this work?

### The defaults

The already available role vars that manage containers are added to every service's `{service}/defaults/mail.conf

- When `*_selinux_enable` is `true` (default), `privileged` evaluates to `false`, meaning containers run without `--privileged` and rel on SELinux policies.
- When `*_selinux_enable` is `false`, containers run with `--privileged` for backward compatibility.

### `security_opt` and labels at container creation

**IMPORTANT** A container must be instantiated with an appropriate
`security_opt` label. If an administrator chooses to try to enable
SELinux on an existing deployment. Any existing container must
redeployed with the appropriate label applied.
This **WILL** cause some interruption of service as those containers
are deleted and redeployed.

### Helper and bootstrap containers

Although it's possible to force a security_opt label on a service, an
installation may need to force a service to run uconfined via
the `--privileged` tag. Additionally, many services utilize service and
helper containers as setup utilities. The process here is to specify the
correct SELinux domain name for a service container and it's helper
containers. That way, when a container throws an AVC `denied` in the SELinux
audit logs the service or container can be more easily identified.

#### For developers

Add bootstrap, init start and stop, and helper container rule sections
to `./defaults`. do this for for each container used to build up or tear down
each service. `./ansible/roles/{service}/defaults/main.yml`

Initial default SELinux policy can be found in
`./ansible/roles/service-selinux/defaults/{service}.yml`

Kolla-ansible will create a policy ruleset for every ontiner it deploys.
If you don't set a policy for a container in Docker, it will run unconfined.

Service roles should include the following vars:

- `{role_name}_selinux_enabled: true`
- `privileged: "{{ not {role_name}_selinux_enable | bool }}"`
- `cap_add`  # list ***optional depending on needed privs.***

#### Unconfined if `ipc_mode` or `pid_mode` are set.

If either `ipc_mode` or `pid_mode` are set for a container
then docker will run it unconfined. Podman may play better. YYMV.

The `_effective_security_opt()` only checks a system for `privileged. It does
**not** check `pid_mode`. So with `privileged=False` + `pid_mode=host`,
the label is still generated and passed to the container runtime, but the
container will still run unconfined.

Sone role may have an additional set of `cap_add` vars available.

#### For admins/operators

**NOTE:** Any container that runs with the `--privileged` tag will ignore any
security_opt label and run in spc_t mode! Trying to divine AVC denials is
difficult. Your best bet is to test your policy configs on a test environment
starting with a kolla-ansible All-in-One installation.

### References

- https://docs.docker.com/reference/cli/docker/container/run/#security-opt
- https://kubernetes.io/docs/concepts/security/linux-kernel-security-constraints/


## Docs

### Role Variables of note

- enable_selinux # default = true
- selinux_profile_build_dir  # default = `/etc/selinux/kolla_custom_profiles`
- kolla_<role_name>_selinux_policies  # optional. Set per role in the `<role_name>/defaults/main.yml` file.

To enable or disable the `selinux` routines:

- **enable_selinux** == <true|false>  # The default is "true".
  - Set to `false` in your site-specific `globals.yml` if your deployment environment is not yet ready to handle SELinux maintenance.
    - For kayobe deploys, set `kolla_enable_selinux:` in your environment.

Variables for service-selinux are organized per service, but defined on a per-container basis. They're currently found in `./ansible/roles/service-selinux/defaults/` but should be move to the individual service defaults.

- **kolla_<service>_selinux_policies**: There only needs to be one of these
per service, but you can create policy for each individual service-related
item if wanted. For example, prometheus has several related services, but
you can create one set of policy that includes several policies, or set a
policy domain for each service or helper container. It's not terribly
complicated, just tedious.

For example, these three containerized services get loaded under a single **prometheus** role, and can be grouped under a similar selinux domain:

- kolla_prometheus
- kolla_prometheus_node_exporter
- kolla_prometheus_alertmanager

### Hosts and group names vs policy application

An individual policy application depend upon of the service will be
installed as defined in "groups".

See `./docs/EXAMPLE_policies_vars.yml` for an example policy format.

Initially, vars come from files loaded from the `service-selinux/defaults/` directory. These can and likely should be the provenance of the individual role maintainers `ansible-kolla/andible/roles/<role_name>/defaults/main.yml` defaults as an additional part per container for consistency.

### Installation process

#### bootstrap-servers

  1. service-selinux bootstrap: install packages, sets selinux state, policy build dir, adds `/etc/docker/daemon.json` to set Docker's launch state to `"selinux-enabled": true`
  2. openstack.kolla.baremetal: docker-ce installs

#### deploy

  3. Deploy as usual, or to update specific container, try:

  ```bash
  export ANSIBLE_LOG_PATH=/opt/logs/ansible-opensearch-$(date "+%Y%m%d-%M").log ;  kolla-ansible deploy --tags selinux,opensearch
```

#### Other Correct invocations:

**native kolla-ansible (canonical)**
- `ansible-playbook -i <inventory> site.yml --tags selinux --limit monitoring,control`

**via kayobe (runs site.yml with the selinux tag)**
- `kayobe kolla ansible run site --tags selinux --limit <monitoring-host>`

### Ad hoc runs

The role also supports limit_selinux_services to restrict work to just
a single service, e.g., opensearch, with an ad-hoc playbook available at: `roles/service-selinux/utils/update_specific_selinux_policies.yml`

...but for a single opensearch.yml defaults change, `--tags selinux` on
site.yml is sufficient -- it detects the "te" checksum change
and recompiles/reinstalls only the stale module. Example:

```bash
kolla-ansible reconfigure -e 'limit_selinux_services=["opensearch","nova","kolla_toolbox"]'
```

***Assume inventory is handled or add inventory: *-i /etc/kolla/ansible/inventory/all-in-one* .***

### Customization and updates

#### About `security_opt` defaults

When Kolla builds the docker variables, `security_opt` is pulled from
each container's entry in `<service_name>/defaults/main.yml` or
`bootstrap_service.yml`. If there is a valid array it will be applied
identically as it was written for that container. If no security_opt entry
exists or evaluates to an empty list, the worker will generate and apply a
fallback list containing: `['label=type:kolla_<container_name>_t']`

Container defaults now need a security_opt key/value if a policy is to be
applied, **but** helper containers are another story. A container
build has to have the service's security_opt label applied in the container's
config.

**Note:** If you must override the default security_opt value, you must provide
a complete list of security_opt values, *including*:
- **['label=type:kolla_<container_name>_t']**

Handle these at your own risk.

#### Custom policies in globals or inventory

Custom policies can be placed in `kolla/globals.yml` or
a Kayobe `environment/inventory/group_vars`
or `./host_vars/` file.

As an example, to provide a custom policy for grafana, you could add a block similar to this:

```bash
yaml
grafana_selinux_policies:
  grafana:
    enabled: true
    groups:
      - "monitoring"
      - "controllers"
    description: "Custom SELinux domain for Grafana UI"
    domain: "my_custom_grafana_t" # This would override the default 'kolla_grafana_t'
    exec_type: "my_custom_grafana_exec_t"
    requires:
      - "type container_runtime_t;"
      - "type port_t;"
      - "class tcp_socket { name_bind name_connect };"
    allow_rules:
      - "allow my_custom_grafana_t port_t:tcp_socket { name_bind name_connect };"

```

### How to update update policy *only* for specific services

A full reconfigure takes well over an hour. To just update policy and hopefully save a little time, we've included a utility playbook you may be able to run via the command line and include the variables for the specific package policies, or:

```bash
ansible-playbook -i ansible/inventory/all-in-one \
  ansible/roles/service-selinux/utils/update_specific_selinux_policies.yml \
  -e 'limit_selinux_services=["prometheus", "kolla_toolbox"]'
 ```

 The limit_selinux_services values must match filenames. If the container name has dashes, substitute underscores instead of dashes for the name, e.g., `kolla_toolbox`, not *kolla-toolbox*.; and `prometheus`, not prometheus_node_exporter (the latter lives inside defaults/prometheus.yml or in the prometheus role defaults).

Any service's `_selinux_policies` can be customized for your deployments by adding site-specific variable overrides. To enable `selinux` for a specific service, you would add service-specific variables for your service.

***Important:*** <em>If a container does not yet have policy applied, adding policy for an existing container that previously did not have policies defined **will disrupt services**.</em>

### Policy setup gotcha - selinux vs _helper containers_

## Run in Kayobe

Here's an example on how you might update containers on the controller nodes:

```bash
kayobe kolla ansible run site --tags selinux --limit your-controllers-*
```

## Dependencies and expectations

- Initial version expects a family of systems based on RedHat and will expect to be able to load a few selinux-related tools for installation and troubleshooting.
- Tested on Rocky 10.2. YMMV.
- Security is hard. Expect things to break.

You can verify with:

```bash
# After bootstrap, before deploy:
rpm -q policycoreutils-python-utils selinux-policy-devel container-selinux
cat /etc/docker/daemon.json
sestatus
```

## After docker install

Check containers with the following:

```bash
docker info | grep -i selinux   # should show "Security Options: selinux"
```

## Tests

Tests for the security_opt updates are found here:

`tests/kolla_container_tests/test_selinux_security_opt.py`

To run just these tests manually:

```bash
cd <path_to>/kolla-ansible
bash tests/link-module-utils.sh $(pwd)
python -m pytest tests/kolla_container_tests/test_selinux_security_opt.py -v
```

## How to find SELinux violations - denied

**List loaded kolla modules**

- `semodule -l | grep kolla`

**List selinux domain info**

- `seinfo -adomain -x  # list all domains`
- `seinfo --type=kolla_opensearch_t --expand`

**List containers and their security_opt labels:**

`docker inspect --format '{{.Name}} | {{.HostConfig.SecurityOpt}}' $(docker ps -q) | column -t -s "|"`

**Looking for issues**

- `sealert -a /var/log/audit/audit.log`  # This is sloooow, but detailed.
- `journalctl -t setroubleshoot`

**Get the label for a speific container**

- `semodule -l | grep fluentd`

**Get selinux issues**

- `ausearch -m avc -ts recent`

**Get issue for a specific issue since last boot**

- `ausearch -m avc --start boot | grep kolla_nova_api_t`

**Confirm the type exists in the loaded policy**

- `seinfo -t kolla_neutron_server_t -x`

**Confirm the container is labelled correctly**
- `docker inspect nova_compute --format '{{.HostConfig.SecurityOpt}}'`

**What is a container allowed to do**
Examples:
- `sesearch --allow --source kolla_cinder_api_t`
- `sesearch --allow --source kolla_prometheus_alertmanager_t`
- `sesearch --allow --source kolla_neutron_server_t`

**Domain summary via seinfo**
Show the domain type exists and its attributes
- `seinfo --type=kolla_prometheus_node_exporter_t --expand`


## License

This content follows the parent [**kolla-ansible** package license](../../../LICENSE).

## Author Information

Direct flogging and complaints to Kurt Bendl.


## TODO

- Consider how to update existing selinux policy for tools such as cron,
  collectd, possibly also apps such as prometheus server that may already have
  selinux profiles. Apps may not be an issue, since we're dealing with
  containers and not on-system apps.
- Determine how to remove an existing policy. Expect collisions.
  (Note: destroy the existing domain; create new.)
- Determine "non-service" policy opportunities such as
  services on the Ansible control and seed nodes.
- Include scripts to compile audit log data for analysis.
- Ingest audit log AVC into OpenSearch and
  - Build grafana dashboards to analyze.
  - AlertManager alerts for labeled policy violations.

### TODO - determine if still needed to make it run

Might need to turn start selinux audit reporting on systems and then off when
done while initially doing testing and development to ensure audit rules have
a chance to write.

    semodule -DB


After applying policies, verify with:

    ausearch -m avc -ts recent | audit2allow
    ansible -m shell -a "sestatus" all
    ansible -m shell -a "docker info | grep -i selinux" all
