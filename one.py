import argparse
import json as j
import logging
import os
import random
import string
import time
from pathlib import Path

import requests


class OneDrive:

    def __init__(self):
        self._api_base_url = 'https://graph.microsoft.com/v1.0/'
        self.logger = logging.getLogger(self.__class__.__name__)
        self.http = requests.session()
        self.response_error = 'error.message'
        self.username = os.environ.get('username')
        self.tenant_id = os.environ.get('tenant_id')
        self.client_id = os.environ.get('client_id')
        self.client_secret = os.environ.get('client_secret')
        self.token = None

    def get_ms_token(self):
        url = f'https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token'
        scope = 'https://graph.microsoft.com/.default'
        post_data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': scope
        }
        result = self.fetch(url, data=post_data).json()
        return result['access_token']

    def upload_file(self, src: Path):
        drive = f'/users/{self.username}/drive/root'
        return self.api(f'{drive}:/{src.name}:/content', method='PUT', data=src.read_bytes())

    def delete_file(self, src: Path):
        drive = f'/users/{self.username}/drive/root'
        return self.api(f'{drive}:/{src.name}:/content', method='DELETE')

    def file_list(self):
        api_params = {'$select': 'id, name', '$top': 10}
        return self.api(f'/users/{self.username}/drive/root/children', api_params)

    def mail_list(self):
        api_params = {'$select': 'id, subject', '$top': 10}
        return self.api(f'/users/{self.username}/messages', api_params)

    def site_list(self):
        api_params = {'search': '*', '$top': 10}
        return self.api('/sites', api_params)

    def user_list(self):
        api_params = {'$select': 'id, userPrincipalName', '$top': 25}
        return self.api('/users', api_params)

    def delete_user(self, user):
        return self.api(f'/users/{user}', method='DELETE')

    def create_user(self, **kwargs):
        _subscribed = random.choice(self.subscribed_list())
        domain = self.get_default_domain()
        password = kwargs.get('password', ''.join(
            random.choices(string.ascii_letters + string.digits + '!#$%&()*+-/:;<=>?@', k=10)))
        username = kwargs.get('username', ''.join(random.choices(string.ascii_letters, k=6)))
        user_email = f'{username}@{domain}'
        post_data = {
            'accountEnabled': True,
            'displayName': username,
            'mailNickname': username,
            'passwordPolicies': 'DisablePasswordExpiration, DisableStrongPassword',
            'passwordProfile': {
                'password': password,
                'forceChangePasswordNextSignIn': False
            },
            'userPrincipalName': user_email,
            'usageLocation': 'HK'
        }
        data = self.api('/users', json=post_data, method='POST')
        self.logger.info(f'{user_email}: {password} 创建完成.')
        if _subscribed and _subscribed.get('sku_id'):
            self._assign_license(user_email, _subscribed['sku_id'])
            self.logger.info(f'{user_email}: 分配订阅完成.')
        return data

    def _assign_license(self, user_email, sku_id):
        api = f'/users/{user_email}/assignLicense'
        post_data = {
            'addLicenses': [
                {
                    'disabledPlans': [],
                    'skuId': sku_id
                }
            ],
            'removeLicenses': []
        }
        return self.api(api, json=post_data)

    def get_default_domain(self):
        data = self.api('/domains')
        for item in data['value']:
            if item.get('isDefault'):
                return item.get('id')
        return None

    def subscribed_list(self):
        subscribed_list = self.api('/subscribedSkus')
        result = []
        for i in subscribed_list['value']:
            if i['capabilityStatus'] == 'Enabled' and i['skuId'] != '6470687e-a428-4b7a-bef2-8a291ad947c9':
                result.append({'status': i['capabilityStatus'], 'sku_id': i['skuId'],
                               'units': f'{i["consumedUnits"]}/{i["prepaidUnits"]["enabled"]}'})
        return result

    def api(self, api_sub_url, params=None, data=None, method=None, **kwargs):
        self.http.headers['Authorization'] = f"Bearer {self.token}"
        if api_sub_url.find('http') == -1:
            url = '{}/{}'.format(self._api_base_url.strip('/'), api_sub_url.strip('/'))
        else:
            url = api_sub_url

        response = self.fetch(url, data=data, method=method, params=params, **kwargs)
        if len(response.content) > 1:
            return response.json()
        return {'status_code': response.status_code}

    def fetch(self, url, data=None, method=None, json=None, **kwargs):
        kwargs.setdefault('timeout', 20)
        if (data or json) and method is None:
            method = 'POST'

        if method is None:
            method = 'GET'
        response = self.http.request(method, url, data=data, json=json, **kwargs)
        if response.ok:
            return response

        raise Exception(response.url, response.status_code, response.text)


def log(data):
    print(j.dumps(data, indent=4))


def script_main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--client-id')
    parser.add_argument('--client-secret')
    parser.add_argument('--tenant-id')
    parser.add_argument('--username')
    parser.add_argument('--action')
    args = parser.parse_args()
    params = vars(args)

    one = OneDrive()
    for k, v in params.items():
        if v and hasattr(one, k):
            setattr(one, k, v)
    one.token = one.get_ms_token()

    if params.get('action'):
        return getattr(one, params.get('action'))()

    name = int(time.time())
    new_file = Path(f'/tmp/{name}.txt')
    new_file.write_text(f'{name}')
    one.upload_file(new_file)
    new_file.unlink()

    files = one.file_list()
    if len(files['value']) > 10:
        for file in files['value']:
            one.delete_file(Path(file['name']))

    one.mail_list()
    log(one.subscribed_list())

    a = random.randint(1, 2)
    if a == 1:
        users = one.user_list()
        if len(users['value']) > 10:
            for user in users['value']:
                if user['userPrincipalName'].find('root'):
                    continue
                one.delete_user(user['userPrincipalName'])
        return {}
    return {}


def main_handler(event, context):
    return script_main()


if __name__ == '__main__':
    script_main()
