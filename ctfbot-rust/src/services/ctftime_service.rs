use chrono::Utc;
use crate::models::CtfEvent;

pub async fn get_ctftime_events() -> Result<Vec<CtfEvent>, reqwest::Error> {
    let now = Utc::now();
    let start = now.to_rfc3339();
    let end = (now + chrono::Duration::weeks(2)).to_rfc3339();
    let url = format!(
        "https://ctftime.org/api/v1/events/?limit=20&start={}&end={}",
        start,
        end
    );
    let events = reqwest::get(&url).await?.json::<Vec<CtfEvent>>().await?;
    Ok(events)
}
