from __future__ import print_function

import json
import os
import subprocess

from clint.textui import puts, colored
from six.moves import shlex_quote

from commcare_cloud.cli_utils import print_command
from commcare_cloud.commands.command_base import CommandBase, Argument
from commcare_cloud.commands.utils import render_template
from commcare_cloud.environment.main import get_environment
from commcare_cloud.environment.paths import TERRAFORM_DIR


class Terraform(CommandBase):
    command = 'terraform'
    help = "Run terraform for this env with the given arguments"

    arguments = (
        Argument('--skip-secrets', action='store_true', help="""
            Skip regenerating the secrets file.

            Good for not having to enter vault password again.
        """),
        Argument('--username', help="""
            The username of the user whose public key will be put on new servers.

            Normally this would be _your_ username.
            Defaults to the username of the user running the command. 
        """),
    )

    def run(self, args, unknown_args):
        environment = get_environment(args.env_name)
        run_dir_root = environment.paths.get_env_file_path('.generated-terraform')
        run_dir = os.path.join(run_dir_root, 'entrypoint')
        modules_dir = os.path.join(TERRAFORM_DIR, 'modules')
        modules_dest = os.path.join(run_dir_root, 'modules')
        if not os.path.isdir(run_dir_root):
            os.mkdir(run_dir_root)
        if not os.path.isdir(run_dir):
            os.mkdir(run_dir)
        if not (os.path.exists(modules_dest) and os.readlink(modules_dest) == modules_dir):
            os.symlink(modules_dir, modules_dest)

        if args.username:
            key_name = args.username
        else:
            import getpass
            key_name = getpass.getuser()

        with open(os.path.join(run_dir, 'terraform.tf'), 'w') as f:
            try:
                print(generate_terraform_entrypoint(environment, key_name), file=f)
            except UnauthorizedUser as e:
                allowed_users = environment.users_config.dev_users.present
                puts(colored.red(
                    "Unauthorized user {}.\n\n"
                    "Use --username to pass in one of the allowed ssh users:{}"
                    .format(e.username, '\n  - '.join([''] + allowed_users))))
                return -1

        if not args.skip_secrets:
            rds_password = environment.get_vault_variables()['secrets']['POSTGRES_USERS']['root']['password']
            with open(os.path.join(run_dir, 'secrets.auto.tfvars'), 'w') as f:
                print('rds_password = {}'.format(json.dumps(rds_password)), file=f)

        env_vars = {'AWS_PROFILE': environment.terraform_config.aws_profile}
        all_env_vars = os.environ.copy()
        all_env_vars.update(env_vars)
        cmd_parts = ['terraform'] + unknown_args
        cmd = ' '.join(shlex_quote(arg) for arg in cmd_parts)
        print_command('cd {}; {} {}; cd -'.format(
            run_dir,
            ' '.join('{}={}'.format(key, value) for key, value in env_vars.items()),
            cmd,
        ))
        return subprocess.call(cmd, shell=True, env=all_env_vars, cwd=run_dir)


class UnauthorizedUser(Exception):
    def __init__(self, username):
        self.username = username


def generate_terraform_entrypoint(environment, key_name):
    context = environment.terraform_config.to_json()
    if key_name not in environment.users_config.dev_users.present:
        raise UnauthorizedUser(key_name)

    context.update({
        'users': [{
            'username': username,
            'public_key': environment.get_authorized_key(username)
        } for username in environment.users_config.dev_users.present],
        'key_name': key_name,
    })
    return render_template('entrypoint.tf.j2', context, os.path.dirname(__file__))
