# selinux_core

SELinux policy for kolla containers via security_opt.

A role to:

1. Add the `--security_opt` flag to all containers.
2. Optionally apply domain labels to each kolla service container.
3. Optionally apply policy rules to each SELinux domain, allowing
   any policy violations to be easily mapped back to the offending
   container.

## TODO

- Need to agree to security_opt naming convention for
  selinux labels. Currently **`kolla_<service>_selinux_policies`**
- Ask the team for input re: from where the vars for
  each project's `<service_name>_selinux_policies` should come.
  Currently supports `./defaults/main.yml` and vars can be loaded
  from service_role/defaults/selinux.yml
- Determine how to remove an existing policy. Expect collisions.
  (Note: destroy the existing domain; create new.)
- Determine "non-service" policy opportunities such as
  services on the Ansible control and seed nodes.
- Include scripts to compile audit log data for analysis.
- Ingest audit log AVC into OpenSearch and
  - Build grafana dashboards to analyze.
  - AlertManager alerts for labeled policy violations.

### TODO to make it run

Might need to turn start selinux audit reporting on systems and then off when done while initially doing testing and development to ensure audit rules have a chance to write.

    semodule -DB

## Requirements

The security_opt label must match the pattern `kolla_<container_name>_t`

For example, in the file `kolla-ansible/ansible/roles/prometheus-node-exporters/defaults/main.yml` under prometheus_service.prometheus-node-exporter, there's a value for the container_name:

    container_name: "prometheus_node_exporter"

The security_opt label attached to the docker command that launches that container would then be: `kolla_prometheus_node_exporter_t` and the corresponding selinux **domain** variable would be `kolla_prometheus_node_exporter_t`.

**IMPORTANT** The domain variable for a container ***must match the security_opt label exactly***, otherwise SELinux audit logs (in audit.log) will not correctly tag AVC denials for the container, and you will find it very difficult to troubleshoot SELinux issues.

The security_opt label must match the pattern `kolla_<container_name>_t`

For example, in the file `kolla-ansible/ansible/roles/prometheus-node-exporters/defaults/main.yml` under prometheus_service.prometheus-node-exporter, there's a value for the container_name:

    container_name: "prometheus_node_exporter"

The security_opt label attached to the docker command that launches that container would then be: `kolla_prometheus_node_exporter_t` and the corresponding selinux **domain** variable would be `kolla_prometheus_node_exporter_t`.

**IMPORTANT** The domain variable for a container ***must match the security_opt label exactly***, otherwise SELinux audit logs (in audit.log) will not correctly tag AVC denials for the container, and you will find it very difficult to troubleshoot SELinux issues.

The security_opt label must match the pattern `kolla_<container_name>_t`

For example, in the file `kolla-ansible/ansible/roles/prometheus-node-exporters/defaults/main.yml` under prometheus_service.prometheus-node-exporter, there's a value for the container_name:

    container_name: "prometheus_node_exporter"

The security_opt label attached to the docker command that launches that container would then be: `kolla_prometheus_node_exporter_t` and the corresponding selinux **domain** variable would be `kolla_prometheus_node_exporter_t`.

**IMPORTANT** The domain variable for a container ***must match the security_opt label exactly***, otherwise SELinux audit logs (in audit.log) will not correctly tag AVC denials for the container, and you will find it very difficult to troubleshoot.

Testing modules required:

    pytest
    oslotest
    docker
    podman

### Tested OSs

- Rocky Linux 9.5
- ansible_os_family == 'RedHat' and ansible_distribution_major_version | int >= 9

### `security_opt` labels at container creation

A container must be instantiated with an appropriate `security_opt`
label. Any existing container must redeployed with the appropriate
label applied. So, this may cause some interruption of service.

### References:

- https://docs.docker.com/reference/cli/docker/container/run/#security-opt
- https://kubernetes.io/docs/concepts/security/linux-kernel-security-constraints/


## Docs

### Role Variables of note

- enable_selinux_core  # default = true
- kolla_selinux_profile_build_dir  # default = `/etc/selinux/kolla_custom_profiles`
- < role_name >_selinux_policies  # optional. Set per role.


### To enable or disable the `selinux_core` routines:

- **enable_selinux_core** == <true|false>  # The default is "true".
  - Set to `false` in your site-specific `globals.yml` if your deployment environment is not yet ready to handle SELinux maintenance.
    For kayobe deploys, set `kolla_enable_selinux_core:` in your environment.

Variables for selinux_core are organized per service, but defined on a per-container basis.

- **kolla_< service >_selinux_policies**: There only needs to be one of these per service, but you can create policy for each individual service-related item if wanted. For example, prometheus had several related services, but you can create one set of policy that includes several policies, or policy domain per sesvice or container type. It's already complicated enough, so make big changes at your own peril.

For example, these three containerized services get loaded under a single **prometheus** role, and can be grouped under a similar selinux domain:

- kolla_prometheus
- kolla_node_exporter
- kolla_alertmanager

An individual policy will only be applied to the node type defined in "groups:".

See `./defaults/EXAMPLE_policies_vars.yml` for an example policy format.

Initially, vars come from files loaded from the `selinux_core/defaults/` directory. These can and likely should be the provenance of the individual role maintainers `ansible-kolla/andible/roles/<role name>/defaults/selinux.yml` role defaults dirs. Pulling these in independent selinux.yml files should make ingesting the vars faster and running the plays more memory efficient.

### Customization and updates

#### About `security_opt` defaults

When Kolla builds the docker variables, `security_opt` is pulled from each container's entry in {service name}/defaults/main.yml. If there is a valid array it will be applied identically as it was written for that container. If no security_opt entry exists or evaluates to an empty list, the worker will generate and apply a fallback list containing ['label=type:kolla_{container_name}_t'].

Instead of updating every single container's variable's list, a default security_opt value is applied if a security_opt var doesn't already exist.

Note: If you must override the default security_opt value, you must provide a complete list of security_opt values, *including* **['label=type:kolla_<container_name>_t']** Handle these at your own risk.

#### Custom policies in globals or inventory

Custom policies can be placed in `kolla/globals.yml` or a Kayobe `environment/inventory/group_vars` or `./host_vars/` file.

As an example, to provide a custom policy for grafana, you could add a block similar to this:

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

#### How to only update update policy for specific services

There are two ways, either via the command line and include the variable, or make a copy of the `./tasks/update_specific_selinux_policies.yml` file and edit the `limit_selinux_services` variable.

Example usage on the command line:

    ansible-playbook -i inventory selinux_core.yml -e '{"limit_selinux_services": ["prometheus", "grafana"]}'

Any service's `_selinux_policies` can be customized for your deployments by adding site-specific variable overrides. To enable `selinux_core` for a specific service, you would add service-specific variables for your service.

Example var to add to your service's variables might be:

    <enabled_selinux_service_name>_selinux_policies:

...using the [example policy file noted above](./defaults/EXAMPLE_policies_vars.yml) as a reference for format.

### Run in Kayobe

Here's an example on how you might update containers on the controller nodes:

    kayobe kolla ansible run setup-selinux --limit your-controllers-*

## Dependencies and expectations

- Initial version expects a family of systems based on RedHat and will expect to be able to load a few selinux-related tools for installation and troubleshooting.
- Tested on Rocky 9.6. YMMV.
- Security is hard. Expect thing sto break.

## Tests

Tests for the security_opt updates were initially generated by Claude, then tweaked by a human. Those can be found here:

    tests/kolla_container_tests/test_selinux_security_opt.py

To run just these tests manually:

    cd <path_to>/kolla-ansible
    bash tests/link-module-utils.sh $(pwd)
    python -m pytest tests/kolla_container_tests/test_selinux_security_opt.py -v

## License

This content follows the parent [**kolla-ansible** package license](../../../LICENSE).

## Author Information

Direct flogging and complaints to Kurt Bendl.
