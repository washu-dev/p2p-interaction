# Public Deployment

The mock demonstration can be published with Streamlit Community Cloud.

## 1. Create a GitHub repository

Create an empty repository in your GitHub account, then run these commands from
the `protein_binder_gui` directory:

```bash
git init
git add .
git commit -m "Initial public Streamlit demo"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

Do not commit `.venv`, uploaded FASTA files, or `.streamlit/secrets.toml`.
The included `.gitignore` excludes them.

## 2. Deploy on Streamlit Community Cloud

1. Sign in at <https://share.streamlit.io/>.
2. Select **Create app**.
3. Choose the GitHub repository and the `main` branch.
4. Set the entry point to `app.py`.
5. Select **Deploy**.

The service installs packages from `requirements.txt`. No secrets are required
for the mock version.

## 3. Share the public URL

After deployment, Streamlit provides a public `*.streamlit.app` URL. Confirm
that app visibility is public in the Community Cloud sharing settings before
distributing the link.

## Public-demo behavior

- Each browser session receives separate Streamlit session state.
- Results and binder sequences are simulated.
- Uploaded files are limited to 5 MB.
- Sequences are limited to 5,000 residues.
- Positive and negative target groups are each limited to 20 records.
- The app does not intentionally write uploaded sequences to persistent storage.
- Session data can disappear when a browser disconnects or the app restarts.

## When moving beyond the mock demo

Do not run long ColabFold or BindCraft jobs inside the Streamlit web process.
Use authentication, a job queue, object storage, a database, per-user quotas,
and isolated GPU workers. Streamlit Community Cloud is appropriate for this
mock demonstration, not for a production GPU design service.
