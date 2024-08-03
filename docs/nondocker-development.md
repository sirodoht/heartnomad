# Non-Docker Development

You will need to setup a PostgreSQL database instance.

Then, create a Python venv and activate it:

```sh
python -m venv .venv
source .venv/bin/activate
```

Now, migrate all tables:

```sh
python manage.py migrate
```

Your docker image is now running with your local development code. Browse to
`http://localhost:8000/` to access your running image. You can run any of the other
`manage.py` commands in the same way. E.g., to run the test suite:

```sh
python manage.py test
```

The first time you get this going, you will want to generate some test data:

```sh
python manage.py generate_test_data
```

This will create a superuser with the credentials `admin` and `password`.

You only need to run these commands once.

To run a dev server:

```sh
python manage.py runserver
```

With debug logging enabled:

```sh
DJANGO_LOG_LEVEL=DEBUG python manage.py runserver
```

## Configuration

You can configure the development environment using environment variables in a file
called `.envrc`. It looks something like this:

```
export STRIPE_SECRET_KEY=...
export STRIPE_PUBLISHABLE_KEY=...
export MAILGUN_API_KEY=...
```

To learn about what can be configured, see the [configuration documentation](configuration.md).
