# Managing Instance

## Create admin

1. Get SSH access to the instance.

```sh
ssh root@modernomad-example.com
```

2. Run:

```sh
sudo -i -u deploy
cd /var/www/modernomad/
source .venv/bin/activate
source .envrc
python manage.py createsuperuser
```

It should look like this:

```
(.venv) deploy@jdxn:/var/www/modernomad$ python manage.py createsuperuser
Username (leave blank to use 'deploy'): admin
Email address: admin@example.com
Password:
Password (again):
Superuser created successfully.
```

## Logs

```sh
ssh root@modernomad-example.com
journalctl -u modernomad
```
