# Deployment

This is how one can set up their own instance of Modernomad. Modernomad is configured
using [ansible](https://github.com/ansible/ansible) scripts (see `ansible/` directory).
These scripts will get you set up with an empty instance on a Debian 12 linux server.

To run:

```sh
cd ansible/
ansible-playbook playbook.yaml -v
```
