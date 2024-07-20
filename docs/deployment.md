# Deployment

This is how one can set up their own instance of Modernomad. Modernomad is configured
using [ansible](https://github.com/ansible/ansible) scripts (see `ansible/` directory).
These scripts will get you set up with an empty instance on a Debian 12 linux server.

To run:

```sh
cd ansible/
ansible-playbook playbook.yaml -v
```

## Auto-deploy using GitHub Actions

We have configuration files for GitHub Actions Continuous Deployment functionality.

This is in `.github/workflows/deploy.yml`.

To set up in one's own repository.

1. Assuming you have SSH access to a Linux server.

2. Go to your repository's 'Settings', then 'Secrets and Variables', then 'Actions'.
This is the direct URL: https://github.com/jdxnlabs/modernomad/settings/secrets/actions
for our repository.

3. Set 'Repository secrets':

- `POSTGRES_PASSWORD` (any random string)
- `SECRET_KEY` (any random string)
- `SSH_KEY` (private key)

4. Set 'Repository cariables':

- `ANSIBLE_HOST` (domain name or IP)
- `ANSIBLE_USER` (user that ansible can connect via SSH)
- `DEBUG` (0 or 1 whether in debug mode)
- `DOMAIN_NAME` (domain name of your modernomad instance — probably the same one as ANSIBLE_HOST)
