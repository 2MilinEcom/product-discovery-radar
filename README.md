# Product Discovery Radar

I built Product Discovery Radar to compare potential products and keep the research in one place. I can scan candidates, inspect scores, and explore content angles before spending more time on a product.

I separated product discovery, content research, and scoring into their own modules. I store results locally and use the dashboard pages to work through the discovery funnel and creative planning.

## Built with

I used Python, Streamlit, pandas, and SQLite.

## Inside the project

* `app.py`: the main dashboard.
* `pages/`: discovery and creative research screens.
* `scanner.py`: product discovery.
* `scoring.py`: product scoring.
* `database.py`: local storage.

## Running it

I install `requirements.txt` in a Python environment and start the dashboard with `streamlit run app.py`. I supply my own integration settings in a local `.env` file.

I treat the scores as research aids, not predictions of sales. Live discovery depends on the configured sources.
