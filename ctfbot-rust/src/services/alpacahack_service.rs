use rusqlite::{Connection, Result};
use crate::models::AlpacaHackInfo;

pub async fn get_alpacahack_info(user: &str) -> Result<Vec<AlpacaHackInfo>, reqwest::Error> {
    let url = format!("https://alpacahack.com/api/user/{}/solves", user);
    let info = reqwest::get(&url).await?.json::<Vec<AlpacaHackInfo>>().await?;
    Ok(info)
}

pub fn create_alpacahack_user_table_if_not_exists() -> Result<()> {
    let conn = Connection::open("alpacahack.db")?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS alpacahack_users (name TEXT NOT NULL UNIQUE)",
        [],
    )?;
    Ok(())
}

pub fn insert_alpacahack_user(name: &str) -> Result<String> {
    let conn = Connection::open("alpacahack.db")?;
    conn.execute("INSERT INTO alpacahack_users (name) VALUES (?1)", [name])?;
    Ok(format!("Added user: {}", name))
}

pub fn delete_alpacahack_user(name: &str) -> Result<String> {
    let conn = Connection::open("alpacahack.db")?;
    conn.execute("DELETE FROM alpacahack_users WHERE name = ?1", [name])?;
    Ok(format!("Deleted user: {}", name))
}

pub fn get_all_alpacahack_users() -> Result<Vec<String>> {
    let conn = Connection::open("alpacahack.db")?;
    let mut stmt = conn.prepare("SELECT name FROM alpacahack_users")?;
    let mut rows = stmt.query([])?;
    let mut users = Vec::new();
    while let Some(row) = rows.next()? {
        users.push(row.get(0)?);
    }
    Ok(users)
}
