# Static Landing Page

This folder contains the safer SEO/social-sharing entry page for `https://tax.contexta.biz/`.

## What it does

- Serves a static landing page at `/`
- Includes full `meta`, `og:*`, and `twitter:*` tags
- Uses your OG image at `/canadian-income-tax-estimator-og.jpg`
- Redirects visitors to the Streamlit app at `/app/`

## Recommended deployment structure

- Serve [index.html](C:\Users\BertWu\Desktop\ontario-tax-estimator\landing\index.html) as `https://tax.contexta.biz/`
- Copy `canadian-income-tax-estimator-og.jpg` to the same public web root
- Proxy `/app/` to your Streamlit process

## Example public web root

```text
/var/www/tax.contexta.biz/
  index.html
  canadian-income-tax-estimator-og.jpg
```

## Nginx

Use [nginx.conf.example](C:\Users\BertWu\Desktop\ontario-tax-estimator\landing\nginx.conf.example) as the starting point.

## Important note

If you move the Streamlit app under `/app/`, update any deployment/start command or reverse proxy rule so Streamlit is reachable there.
