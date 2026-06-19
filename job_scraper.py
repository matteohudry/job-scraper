#!/usr/bin/env python3
"""
Job Scraper - Mattéo Hudry
Scrape les offres d'emploi sur plusieurs sites et envoie un email quotidien.

Installation des dépendances :
    pip install requests beautifulsoup4 schedule

Configuration :
    1. Renseigne SMTP_PASSWORD avec ton mot de passe d'application Gmail
       (Compte Google > Sécurité > Mots de passe des applications)
    2. Lance le script : python job_scraper.py
    3. Il tourne en continu et envoie un email chaque jour à midi.
"""

import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import time
import schedule
import logging
import json
import re
from urllib.parse import urlencode, quote_plus

# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────

RECIPIENT_EMAIL = "matteo.hudry@gmail.com"
SENDER_EMAIL    = "matteo.hudry@gmail.com"
import os
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
print(f"DEBUG - Longueur du mot de passe recu : {len(SMTP_PASSWORD)} caracteres")
print(f"DEBUG - Premier et dernier caractere : '{SMTP_PASSWORD[:1]}' ... '{SMTP_PASSWORD[-1:]}'")

KEYWORDS = [
    "contrôleur de gestion",
    "analyste financier",
    "analyste financement de projets",
    "associé financement de projets",
    "chargé d'affaires financement de projets",
    "analyste FP&A",
    "analyste M&A infrastructure",
    "analyste M&A ENR",
    "associate M&A infrastructure",
    "associate M&A ENR",
    # Mots-clés supplémentaires adaptés au CV de Mattéo
    "analyste private equity infrastructure",
    "chargé de financement structuré",
    "analyste fusions acquisitions infrastructure",
    "project finance analyst",
    "infrastructure finance",
]

LOCATIONS = ["Lyon", "Annecy", "Genève", "Grenoble"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("job_scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# SCRAPERS PAR SITE
# ──────────────────────────────────────────────

def scrape_hellowork(keyword: str, location: str) -> list[dict]:
    """HelloWork – recherche classique par mot-clé + ville."""
    jobs = []
    try:
        params = {"k": keyword, "l": location, "d": "25"}
        url = f"https://www.hellowork.com/fr-fr/emploi/recherche.html?{urlencode(params)}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        for card in soup.select("li[data-id]")[:10]:
            title_el = card.select_one("a[data-cy='offerTitle']")
            company_el = card.select_one("span[data-cy='offerCompany']")
            loc_el = card.select_one("span[data-cy='offerLocation']")
            date_el = card.select_one("span[data-cy='offerPublicationDate']")
            if not title_el:
                continue
            href = title_el.get("href", "")
            jobs.append({
                "title":   title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True) if company_el else "",
                "location": loc_el.get_text(strip=True) if loc_el else location,
                "date":    date_el.get_text(strip=True) if date_el else "",
                "url":     f"https://www.hellowork.com{href}" if href.startswith("/") else href,
                "source":  "HelloWork",
            })
    except Exception as e:
        log.warning(f"HelloWork [{keyword} / {location}] : {e}")
    return jobs


def scrape_welcometothejungle(keyword: str, location: str) -> list[dict]:
    """Welcome to the Jungle – API publique."""
    jobs = []
    try:
        params = {
            "query": keyword,
            "aroundQuery": location,
            "aroundRadius": 20000,
            "page": 0,
        }
        url = f"https://www.welcometothejungle.com/api/v2/jobs?{urlencode(params)}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        data = r.json()

        for hit in data.get("jobs", {}).get("hits", [])[:10]:
            slug = hit.get("slug", "")
            jobs.append({
                "title":    hit.get("name", ""),
                "company":  hit.get("organization", {}).get("name", ""),
                "location": hit.get("office", {}).get("city", location),
                "date":     hit.get("published_at", "")[:10],
                "url":      f"https://www.welcometothejungle.com/fr/companies/{hit.get('organization',{}).get('slug','')}/jobs/{slug}",
                "source":   "Welcome to the Jungle",
            })
    except Exception as e:
        log.warning(f"WTTJ [{keyword} / {location}] : {e}")
    return jobs


def scrape_apec(keyword: str, location: str) -> list[dict]:
    """APEC – API REST publique."""
    jobs = []
    LOCATION_CODES = {
        "Lyon":      "69",
        "Annecy":    "74",
        "Grenoble":  "38",
        "Genève":    None,  # Genève = Suisse, hors périmètre APEC
    }
    dept = LOCATION_CODES.get(location)
    if not dept:
        return jobs
    try:
        payload = {
            "motsCles": keyword,
            "typesContrat": [],
            "niveauFormation": [],
            "fonctions": [],
            "departements": [dept],
            "nombreResultats": 10,
            "pagination": 1,
        }
        url = "https://www.apec.fr/cms/webservices/rechercheOffre/complexe"
        r = requests.post(url, json=payload, headers=HEADERS, timeout=15)
        data = r.json()

        for item in data.get("resultats", []):
            numA = item.get("numeroOffre", "")
            jobs.append({
                "title":    item.get("intitule", ""),
                "company":  item.get("nomEntreprise", ""),
                "location": item.get("lieuDeTravail", location),
                "date":     item.get("datePublication", "")[:10],
                "url":      f"https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/{numA}",
                "source":   "APEC",
            })
    except Exception as e:
        log.warning(f"APEC [{keyword} / {location}] : {e}")
    return jobs


def scrape_jobteaser(keyword: str, location: str) -> list[dict]:
    """JobTeaser – scraping HTML."""
    jobs = []
    try:
        params = {"contract_type": "", "keywords": keyword, "location": location, "radius": 20}
        url = f"https://www.jobteaser.com/fr/job-offers?{urlencode(params)}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        for card in soup.select("article.jt-JobCard")[:10]:
            title_el = card.select_one("h2.jt-JobCard-title")
            company_el = card.select_one("span.jt-JobCard-company")
            loc_el = card.select_one("span.jt-JobCard-location")
            a_el = card.select_one("a.jt-JobCard-link")
            if not title_el:
                continue
            href = a_el["href"] if a_el else ""
            jobs.append({
                "title":    title_el.get_text(strip=True),
                "company":  company_el.get_text(strip=True) if company_el else "",
                "location": loc_el.get_text(strip=True) if loc_el else location,
                "date":     "",
                "url":      f"https://www.jobteaser.com{href}" if href.startswith("/") else href,
                "source":   "JobTeaser",
            })
    except Exception as e:
        log.warning(f"JobTeaser [{keyword} / {location}] : {e}")
    return jobs


def scrape_efinancialcareers(keyword: str, location: str) -> list[dict]:
    """eFinancialCareers – scraping HTML."""
    jobs = []
    try:
        params = {"keywords": keyword, "location": location, "radius": 20, "currencyCode": "EUR"}
        url = f"https://www.efinancialcareers.fr/search?{urlencode(params)}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        for card in soup.select("article.job-card")[:10]:
            title_el = card.select_one("h3.job-card__title a")
            company_el = card.select_one("span.job-card__company")
            loc_el = card.select_one("span.job-card__location")
            date_el = card.select_one("span.job-card__date")
            if not title_el:
                continue
            href = title_el.get("href", "")
            jobs.append({
                "title":    title_el.get_text(strip=True),
                "company":  company_el.get_text(strip=True) if company_el else "",
                "location": loc_el.get_text(strip=True) if loc_el else location,
                "date":     date_el.get_text(strip=True) if date_el else "",
                "url":      f"https://www.efinancialcareers.fr{href}" if href.startswith("/") else href,
                "source":   "eFinancialCareers",
            })
    except Exception as e:
        log.warning(f"eFinancialCareers [{keyword} / {location}] : {e}")
    return jobs


def scrape_linkedin(keyword: str, location: str) -> list[dict]:
    """
    LinkedIn – scraping HTML de l'endpoint public (sans connexion).
    Note : LinkedIn limite fortement le scraping ; pour un usage intensif,
    utilise l'API officielle ou un outil tiers (Apify, Bright Data).
    """
    jobs = []
    try:
        params = {
            "keywords": keyword,
            "location": location,
            "f_TPR": "r86400",  # dernières 24h
            "distance": 25,
            "start": 0,
        }
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{urlencode(params)}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        for card in soup.select("li")[:10]:
            title_el = card.select_one("h3.base-search-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle")
            loc_el = card.select_one("span.job-search-card__location")
            date_el = card.select_one("time")
            a_el = card.select_one("a.base-card__full-link")
            if not title_el:
                continue
            jobs.append({
                "title":    title_el.get_text(strip=True),
                "company":  company_el.get_text(strip=True) if company_el else "",
                "location": loc_el.get_text(strip=True) if loc_el else location,
                "date":     date_el.get("datetime", "") if date_el else "",
                "url":      a_el["href"] if a_el else "",
                "source":   "LinkedIn",
            })
    except Exception as e:
        log.warning(f"LinkedIn [{keyword} / {location}] : {e}")
    return jobs


# ──────────────────────────────────────────────
# COLLECTE & DÉDUPLICATION
# ──────────────────────────────────────────────

SCRAPERS = [
    scrape_linkedin,
    scrape_efinancialcareers,
    scrape_welcometothejungle,
    scrape_hellowork,
    scrape_jobteaser,
    scrape_apec,
]


def collect_all_jobs() -> list[dict]:
    seen_urls = set()
    all_jobs = []

    for keyword in KEYWORDS:
        for location in LOCATIONS:
            log.info(f"  Recherche : '{keyword}' @ {location}")
            for scraper in SCRAPERS:
                results = scraper(keyword, location)
                for job in results:
                    url = job.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        job["keyword"] = keyword
                        all_jobs.append(job)
                time.sleep(1)  # politesse envers les serveurs

    log.info(f"Total offres collectées (dédupliquées) : {len(all_jobs)}")
    return all_jobs


def filter_recent(jobs: list[dict], hours: int = 24) -> list[dict]:
    """Garde uniquement les offres publiées dans les dernières `hours` heures."""
    cutoff = datetime.now() - timedelta(hours=hours)
    recent = []
    for job in jobs:
        raw_date = job.get("date", "")
        if not raw_date:
            # Date inconnue → on l'inclut par précaution
            recent.append(job)
            continue
        try:
            # Formats courants : YYYY-MM-DD ou YYYY-MM-DDTHH:MM:SS
            pub = datetime.fromisoformat(raw_date[:19])
            if pub >= cutoff:
                recent.append(job)
        except ValueError:
            recent.append(job)
    return recent


# ──────────────────────────────────────────────
# EMAIL HTML
# ──────────────────────────────────────────────

def build_html_email(jobs: list[dict]) -> str:
    today = datetime.now().strftime("%d/%m/%Y")
    source_colors = {
        "LinkedIn":             "#0A66C2",
        "eFinancialCareers":    "#1B3A6B",
        "Welcome to the Jungle":"#3D1173",
        "HelloWork":            "#FF6B35",
        "JobTeaser":            "#E63946",
        "APEC":                 "#003189",
    }

    # Regroupement par source
    by_source: dict[str, list] = {}
    for job in jobs:
        src = job.get("source", "Autre")
        by_source.setdefault(src, []).append(job)

    sections_html = ""
    for source, items in by_source.items():
        color = source_colors.get(source, "#555")
        cards = ""
        for j in items:
            cards += f"""
            <tr>
              <td style="padding:12px 0;border-bottom:1px solid #eee;">
                <a href="{j['url']}" style="font-size:15px;font-weight:600;color:{color};text-decoration:none;">
                  {j['title']}
                </a><br>
                <span style="font-size:13px;color:#444;">{j['company']}</span>
                &nbsp;·&nbsp;
                <span style="font-size:13px;color:#888;">{j['location']}</span>
                {f'&nbsp;·&nbsp;<span style="font-size:12px;color:#aaa;">{j["date"]}</span>' if j.get("date") else ""}
                <br>
                <span style="font-size:11px;color:#aaa;">Mot-clé : {j.get('keyword','')}</span>
              </td>
            </tr>"""

        sections_html += f"""
        <tr><td style="padding-top:28px;">
          <h2 style="margin:0 0 8px;font-size:16px;color:{color};border-left:4px solid {color};padding-left:10px;">
            {source} <span style="font-weight:400;color:#999;font-size:13px;">({len(items)} offre{'s' if len(items)>1 else ''})</span>
          </h2>
          <table width="100%" cellpadding="0" cellspacing="0">{cards}</table>
        </td></tr>"""

    if not jobs:
        sections_html = """<tr><td style="padding:24px 0;color:#888;text-align:center;">
            Aucune nouvelle offre dans les dernières 24h.</td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:32px 0;">
  <tr><td align="center">
    <table width="620" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.07);">

      <!-- Header -->
      <tr><td style="background:#1B3A6B;padding:24px 32px;">
        <h1 style="margin:0;color:#fff;font-size:20px;">📊 Offres du {today}</h1>
        <p style="margin:4px 0 0;color:#a8c4e0;font-size:13px;">
          {len(jobs)} nouvelle{'s' if len(jobs)!=1 else ''} offre{'s' if len(jobs)!=1 else ''} · Lyon · Annecy · Grenoble · Genève
        </p>
      </td></tr>

      <!-- Body -->
      <tr><td style="padding:16px 32px 32px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          {sections_html}
        </table>
      </td></tr>

      <!-- Footer -->
      <tr><td style="background:#f9f9f9;padding:16px 32px;border-top:1px solid #eee;">
        <p style="margin:0;font-size:11px;color:#aaa;text-align:center;">
          Email généré automatiquement par job_scraper.py · {datetime.now().strftime("%d/%m/%Y %H:%M")}
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""


def send_email(jobs: list[dict]) -> None:
    today = datetime.now().strftime("%d/%m/%Y")
    subject = f"🔍 {len(jobs)} offres d'emploi – {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECIPIENT_EMAIL

    # Version texte brut
    plain = f"Offres d'emploi du {today}\n\n"
    for j in jobs:
        plain += f"[{j['source']}] {j['title']} – {j['company']} – {j['location']}\n{j['url']}\n\n"
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(build_html_email(jobs), "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(SENDER_EMAIL, SMTP_PASSWORD)
            smtp.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        log.info(f"Email envoye : {len(jobs)} offres -> {RECIPIENT_EMAIL}")
    except Exception as e:
        log.error(f"Échec envoi email : {e}")


# ──────────────────────────────────────────────
# TÂCHE QUOTIDIENNE
# ──────────────────────────────────────────────

def daily_job() -> None:
    log.info("=== Lancement de la collecte quotidienne ===")
    all_jobs = collect_all_jobs()
    recent   = filter_recent(all_jobs, hours=24)
    log.info(f"Offres récentes (< 24h) : {len(recent)}")
    send_email(recent)


# ──────────────────────────────────────────────
# POINT D'ENTRÉE
# ──────────────────────────────────────────────

if __name__ == "__main__":
    daily_job()
