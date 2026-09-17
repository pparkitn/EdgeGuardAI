# Setting up AWS credentials for Amazon Polly (console-only steps)

## 1. Sign in & pick region
- Go to https://aws.amazon.com/console → **Sign in to the Console**
- **Important:** the region shown in the top-right corner must be **US East (N. Virginia) / us-east-1** (your code uses `us-east-1`, `voice/config.py:14`). If not, click it → search `us-east-1` → select **US East (N. Virginia)**.

## 2. Create the IAM user
- In the top search bar, type `IAM` → click **IAM** (Access management)
- Left sidebar → **Users** → **Create user**
- **User name:** `polly-user`
- Check **Provide user access to the AWS Management Console** (optional — needed only if you want to log in as this user; for API-only you can leave it unchecked)
- Leave **Group** empty → **Next**
- **Skip tags** → **Next**
- **Create user**

## 3. Attach a Polly-only permission policy
- On the user's detail page → **Permissions** tab → **Add permissions** → **Create policy** → **JSON**
- Delete the template and paste:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "polly:SynthesizeSpeech",
            "Resource": "*"
        }
    ]
}
```
- **Next** → **Next** → **Policy name:** `PollyOnly` → **Create policy**
- Back on the user page → **Add permissions** → **Attach policies directly** → search `PollyOnly` → tick it → **Next** → **Add permissions**

## 4. Create the Access Key
- On `polly-user` page → **Security credentials** tab (may say **Access keys**)
- **Create access key**
- Use case: **Application code** → **Next**
- **Create access key**
- **This is the only time you'll see the secret** → click **Download .csv** and save it safely (contains `Access key ID` and `Secret access key`)

## 5. Install & configure AWS CLI locally
```bash
pip install awscli
aws configure --profile polly
# AWS Access Key ID:      <paste from CSV>
# AWS Secret Access Key:  <paste from CSV>
# Default region name:    us-east-1
# Default output format:  json
```
This writes `~/.aws/credentials` with a `[polly]` profile — no other profiles are touched.

## 6. Run & verify
```bash
AWS_PROFILE=polly aws polly describe-voices --region us-east-1   # should list voices
AWS_PROFILE=polly aws s3 ls                                      # should fail: AccessDenied
AWS_PROFILE=polly python -c "import sys; sys.path.insert(0,'voice'); from polly import PollyClient; print(PollyClient().synthesize('hello'))"
```

## 7. Security notes
- Delete the keys from your terminal history: `history -c` or clear the shell where you pasted them.
- If the CSV leaks, delete the key in **Security credentials → Delete** and create a new one.
- Your region is already set in code (`voice/config.py:14`), so just remember to export `AWS_PROFILE=polly` whenever you run the app — or add it to the systemd unit / shell profile that launches your broadcaster.